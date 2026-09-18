#!/usr/bin/env python3
"""DJI Cloud API MQTT backend, controller/product agnostic."""
import json, logging, os, signal, sys, time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

load_dotenv()

def env(name, default=None):
    v=os.environ.get(name, default)
    return default if v in (None, "") else v

MQTT_HOST=env("MQTT_HOST")
if not MQTT_HOST: raise ValueError("Environment variable MQTT_HOST is not set.")
MQTT_PORT=int(env("MQTT_PORT","1883")); MQTT_KEEPALIVE=int(env("MQTT_KEEPALIVE","60"))
MQTT_USERNAME=env("MQTT_USERNAME"); MQTT_PASSWORD=env("MQTT_PASSWORD")
RAW_MESSAGES=env("RAW_MESSAGES","0")=="1"; LOG_LEVEL=env("LOG_LEVEL","INFO").upper()
logging.basicConfig(level=getattr(logging,LOG_LEVEL,logging.INFO),format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("dji-cloud-mqtt")

@dataclass
class Device:
    sn:str; domain:Any=None; type:Any=None; sub_type:Any=None; index:Any=None
    device_secret:Optional[str]=None; nonce:Optional[str]=None; thing_version:Optional[str]=None
    parent_gateway:Optional[str]=None; raw:Dict[str,Any]=field(default_factory=dict)

@dataclass
class Gateway:
    sn:str; domain:Any=None; type:Any=None; sub_type:Any=None
    device_secret:Optional[str]=None; nonce:Optional[str]=None; thing_version:Optional[str]=None
    sub_devices:Dict[str,Device]=field(default_factory=dict); raw:Dict[str,Any]=field(default_factory=dict)

gateways:Dict[str,Gateway]={}

def pretty(x):
    return json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)

def parse_json(payload):
    try: x=json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as e:
        log.warning("Invalid JSON payload: %s",e); return None
    return x if isinstance(x,dict) else None

def parse_topic(topic):
    p=topic.split("/")
    if len(p)>=4 and p[:2]==["sys","product"]:
        return "sys",p[2],p[3:]
    if len(p)>=4 and p[:2]==["thing","product"]:
        return "thing",p[2],p[3:]
    return None,None,[]

def register_topology(sn,message):
    d=message.get("data") or {}
    g=Gateway(sn=sn,domain=d.get("domain"),type=d.get("type"),sub_type=d.get("sub_type"),
              device_secret=d.get("device_secret"),nonce=d.get("nonce"),thing_version=d.get("thing_version"),raw=d)
    for item in d.get("sub_devices") or []:
        if not isinstance(item,dict) or not item.get("sn"): continue
        dev=Device(sn=item["sn"],domain=item.get("domain"),type=item.get("type"),sub_type=item.get("sub_type"),
                   index=item.get("index"),device_secret=item.get("device_secret"),nonce=item.get("nonce"),
                   thing_version=item.get("thing_version"),parent_gateway=sn,raw=item)
        g.sub_devices[dev.sn]=dev
    old=gateways.get(sn); gateways[sn]=g
    log.info("TOPOLOGY gateway=%s domain=%s type=%s sub_type=%s thing=%s sub_devices=%d",sn,g.domain,g.type,g.sub_type,g.thing_version,len(g.sub_devices))
    for dev in g.sub_devices.values():
        log.info("  SUB_DEVICE sn=%s domain=%s type=%s sub_type=%s index=%s thing=%s",dev.sn,dev.domain,dev.type,dev.sub_type,dev.index,dev.thing_version)
    if old and set(old.sub_devices)!=set(g.sub_devices):
        log.info("TOPOLOGY CHANGE gateway=%s old=%s new=%s",sn,sorted(old.sub_devices),sorted(g.sub_devices))

def reply_to_update_topo(client,topic,message):
    ts=message.get("timestamp"); ts=int(ts)+2 if isinstance(ts,(int,float)) else int(time.time()*1000)
    reply={"tid":message.get("tid"),"bid":message.get("bid"),"timestamp":ts,"data":{"result":0}}
    info=client.publish(topic+"_reply",json.dumps(reply),qos=0)
    log.info("UPDATE_TOPO_REPLY topic=%s mid=%s",topic+"_reply",getattr(info,"mid",None))

def handle_thing(sn,parts,message):
    section=parts[0] if parts else ""; direction="/".join(parts[1:])
    data=message.get("data") or {}
    if section=="osd":
        log.info("OSD product=%s lat=%s lon=%s height=%s battery=%s head=%s pitch=%s roll=%s",sn,data.get("latitude"),data.get("longitude"),data.get("height"),data.get("battery"),data.get("attitude_head"),data.get("attitude_pitch"),data.get("attitude_roll"))
    elif section=="state": log.info("STATE product=%s keys=%s",sn,sorted(data.keys()))
    elif section=="events": log.info("EVENT product=%s method=%s",sn,message.get("method"))
    elif section=="services_reply": log.info("SERVICE_REPLY product=%s method=%s result=%s",sn,message.get("method"),data.get("result"))
    elif section=="property": log.info("PROPERTY product=%s direction=%s method=%s",sn,direction,message.get("method"))
    elif section=="drc": log.info("DRC product=%s direction=%s method=%s seq=%s",sn,direction,message.get("method"),message.get("seq"))
    else: log.info("THING product=%s section=%s direction=%s method=%s",sn,section,direction,message.get("method"))
    if RAW_MESSAGES: log.info("THING_PAYLOAD:\n%s",pretty(message))

def on_connect(client,userdata,flags,rc,properties=None):
    log.info("Connected to MQTT broker %s:%s rc=%s",MQTT_HOST,MQTT_PORT,rc)
    client.subscribe("sys/product/#",qos=0); client.subscribe("thing/product/#",qos=0)

def on_disconnect(client,userdata,*args): log.warning("Disconnected from MQTT broker args=%s",args)

def on_message(client,userdata,msg):
    m=parse_json(msg.payload)
    if m is None: return
    kind,sn,parts=parse_topic(msg.topic)
    if kind=="sys":
        section=parts[0] if parts else ""
        if section=="status" and m.get("method")=="update_topo":
            register_topology(sn,m); reply_to_update_topo(client,msg.topic,m)
        else:
            log.info("SYS product=%s section=%s method=%s",sn,section,m.get("method"))
            if RAW_MESSAGES: log.info("SYS_PAYLOAD:\n%s",pretty(m))
    elif kind=="thing": handle_thing(sn,parts,m)
    else:
        log.info("OTHER topic=%s",msg.topic)
        if RAW_MESSAGES: log.info("OTHER_PAYLOAD:\n%s",pretty(m))

def make_client():
    try: c=mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,transport="tcp")
    except (AttributeError,TypeError): c=mqtt.Client(transport="tcp")
    if MQTT_USERNAME is not None: c.username_pw_set(MQTT_USERNAME,MQTT_PASSWORD)
    c.on_connect=on_connect; c.on_disconnect=on_disconnect; c.on_message=on_message
    return c

def main():
    c=make_client()
    def stop(sig,frame):
        log.info("Stopping MQTT backend..."); c.disconnect(); sys.exit(0)
    signal.signal(signal.SIGINT,stop); signal.signal(signal.SIGTERM,stop)
    log.info("Starting DJI Cloud API MQTT backend (dynamic topology mode)")
    log.info("Broker: %s:%s",MQTT_HOST,MQTT_PORT)
    c.connect(MQTT_HOST,MQTT_PORT,MQTT_KEEPALIVE); c.loop_forever()

if __name__=="__main__": main()
