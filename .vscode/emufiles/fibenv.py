import lupa
from lupa import LuaRuntime
import threading
from threading import Thread
from threading import Timer
from threading import active_count
import multiprocessing
import logging
import requests
from requests import exceptions
import queue
from collections import deque
import json
import time, sys, os
from datetime import datetime
import fibapi, fibnet

MAX_EVENTS = 400

def convertLuaTable(obj):
    if lupa.lua_type(obj) == 'table':
        if obj[1] and not obj['_dict']:
            b = [convertLuaTable(v) for k,v in obj.items()]
            return b
        else:
            d = dict()
            for k,v in obj.items():
                if k != '_dict':
                    d[k] = convertLuaTable(v)
            return d
    else:
        return obj

def tofun(fun):
    a = type(fun)
    return fun[1] if type(fun) == tuple else fun

def setLogLevel(level: str) -> bool:
    try:
        logging.getLogger().setLogLevel(upper(str))
        return True
    except:
        return False

class FibaroEnvironment:
    def __init__(self, config):
        self.config = config
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.queue = queue.Queue()
        self.eventCount = 0

    def postEvent(self,event,extra=None): # called from another thread
        self.queue.put((event,extra))  # safely qeued for lua thread
    
    def luaCall(self,method,*args): # called from another thread
        try: # unsafe call to lua function in other thread
            QA = self.globals.QA[1] if type(self.globals.QA) == tuple else self.globals.QA
            fun = QA.fun              
            fun = tofun(fun)[method]
            res,code = tofun(fun)(*args)
            res = convertLuaTable(res)
        except Exception as e:
            print(f"Python->Lua Call Error: {e}",file=sys.stderr)
        return res,code or 501

    def refreshStates(self,start,url,options):
        if self.config.get('local'):
            return
        options = convertLuaTable(options)
        def refreshRunner():
            last,retries = 0,0
            while True:
                try:
                    nurl = url + str(last)
                    resp = requests.get(nurl, headers = options['headers'])
                    if resp.status_code == 200:
                        data = resp.json()
                        last = data['last'] if data['last'] else last
                        if data.get('events'):
                            for event in data['events']:
                                self.postEvent({"type":"refreshStates","event":event})
                    elif resp.status_code == 401:
                        print(f"HC3 credentials error",file=sys.stderr)
                        print(f"Exiting refreshStates loop",file=sys.stderr)
                        return
                except exceptions.ConnectionError as e:
                    retries += 1
                    if retries > 5:
                        print(f"Connection error: {nurl}",file=sys.stderr)
                        print(f"Exiting refreshStates loop",file=sys.stderr)
                        return
                except Exception as e:
                    print(f"Error: {e} {nurl}",file=sys.stderr)
                    
        self.rthread = Thread(target=refreshRunner, args=())
        self.rthread.start()

    def addEvent(self,event):
        event = json.loads(event)
        self.eventCount += 1
        event = {'last': self.eventCount, 'event':event}
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            self.events.popleft()

    def getEvents(self,counter):
        events = self.events
        count = events[-1]['last'] if events else 0
        evs = [e['event'] for e in events if e['last'] > counter]
        ts = datetime.now().timestamp()
        tsm = time.time()
        res = dict(
            status='IDLE',
            events=evs,
            changes=[],
            timestamp = ts,
            timestampMillis = tsm,
            date = datetime.fromtimestamp(ts).strftime('%H:%M | %d.%m.%Y'),
            last=count
            )
        return res

    def run(self):

        def runner():
            config = self.config
            globals = self.lua.globals()
            self.globals = globals
            self.events = deque()
            hooks = {
                'clock':time.time,
                'http':fibnet.httpCall,
                'httpAsync':lambda method, url, options, data, local: fibnet.httpCallAsync(self, method, url, options, data, local),
                'refreshStates':lambda start, url, options: self.refreshStates(start,url,options),
                'createTCPSocket':lambda: fibnet.LuaTCPSocket(self),
                'createUDPSocket':lambda: fibnet.LuaUDPSocket(self),
                'createWebSocket':lambda url,headers,cb: fibnet.LuaWebSocket(self,url,headers,cb),
                'listDir':lambda d: json.dumps(os.listdir(d)),
                'deletFile':os.remove,
                'setLogLevel':setLogLevel,
                'exit':lambda code: sys.exit(code)
            }
            luapath = config['path'] + "lua/"
            emulator = luapath + config['emulator']
            f = self.lua.eval(f'function(config,hooks,path) loadfile("{emulator}")(config,hooks,path) end')
            f(json.dumps(config),self.lua.table_from(hooks),luapath)
            QA = globals.QA
            self.DIR =globals.DIR
            self.QA = QA
            self.QA.addEvent = lambda e: self.addEvent(e)
            if config['init']:
                QA.runFile(config['init'])
            if config['file1']:
                self.postEvent({"type":"installQA","file":config['file1']})
            if config['file2']:
                self.postEvent({"type":"installQA","file":config['file2']})
            if config['file3']:
                self.postEvent({"type":"installQA","file":config['file3']})
            while not QA.isDead: # main loop, repeatadly call QA.dispatcher with events
                delay = QA.dispatcher()
                # print(f"event: {delay}s", end='',file=sys.stderr)
                try:
                    event = self.queue.get(block=True, timeout=delay)
                except queue.Empty:
                    event = None
                # print(f", {self.event}",file=sys.stderr)
                if event:
                    try:
                        QA.onEvent(json.dumps(event[0]),event[1])
                    except Exception as e:
                        print(f"onEvent Error: {e}",file=sys.stderr)
                time.sleep(0.001)
            print(f"Exit - threads left:{active_count()}",file=sys.stderr)
            exit(0)
        self.thread = Thread(target=runner,  args=())
        self.thread.start()
