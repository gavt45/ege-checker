# -*- coding: utf-8 -*-

import requests
from time import sleep
from random import randint,choice
from traceback import format_exc
import threading
import json
from os import path
from telethon.sync import TelegramClient, events
import asyncio
import queue
import sys
import logging

callback_queue = queue.Queue()

FORMAT = '%(asctime)-15s %(thread)d %(threadName)s %(message)s'
logging.basicConfig(format=FORMAT,
                    level=logging.INFO)
logger = logging.getLogger('ege_checker')

class Unbuffered(object):
   def __init__(self, stream):
       self.stream = stream
   def write(self, data):
       self.stream.write(data)
       self.stream.flush()
   def writelines(self, datas):
       self.stream.writelines(datas)
       self.stream.flush()
   def __getattr__(self, attr):
       return getattr(self.stream, attr)

sys.stdout = Unbuffered(sys.stdout)

def init_tg_cli(TG_APP_ID, TG_APP_TOKEN):
    global client
    client = TelegramClient('somesess',
                            int(TG_APP_ID),
                            TG_APP_TOKEN,
                            proxy=None)

def request_push_on_main_thread(func_to_call_from_main_thread):
    callback_queue.put(func_to_call_from_main_thread)

def get_and_make_push():
    callback = callback_queue.get() #blocks until an item is available
    callback()

def make_push(id, push):
    global client
    with client:
        client.send_message(id, push)

class CheckerThread(threading.Thread):
    def __init__(self, useragents, cfg, cookie, username, norm_exam_count):
        threading.Thread.__init__(self)
        logger.info("Initializing thread!")
        self.useragents = useragents
        self.base_time = cfg['min_wait'] * 60
        self.max_time = cfg['max_wait'] * 60
        self.cfg = cfg
        self.username = username
        self.cookie = cookie
        self.norm_exam_count = norm_exam_count
        self.stopping = False

        self.setName(self.getName()+"-"+self.username)
    
    def run(self):
        logger.info("Running!")
        sl = 0
        while not self.stopping:
            if sl <= 0:
                res = self.make_request()
                try:
                    if len(res["Result"]["Exams"]) > self.norm_exam_count:
                        logger.critical("EST PROBITIE")
                        logger.critical("RES: {}".format(res))
                        # self.cfg["norm_exam_count"] += 1
                        self.norm_exam_count += 1
                        # json.dump(self.cfg, open('cfg.json','w'))
                        request_push_on_main_thread(lambda: make_push(self.username, "[ЕГЭ] ПОЯВИЛИСЬ РЕЗЫ!!!: ```{}```".format(res)))
                    logger.debug("RES: {}".format(res))
                except:
                    err = format_exc()
                    logger.info(f"WARN: error on res: {res}; ex: {err}")
                sl = randint(self.base_time, self.max_time)
                logger.info("Sleeping for {}".format(float(sl)/60.0))
            sl -= 1
            sleep(1)

    def stop(self):
        logger.info("{} stopping!".format(self.getName()))
        self.stopping = True

    def make_request(self):
        logger.info("Making request!")
        resp_str, resp_code = None, None
        try:
            cookies = {
                'Participant': self.cookie,
            }

            headers = {
                'Connection': 'keep-alive',
                'Accept': '*/*',
                # 'DNT': '1',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': choice(self.useragents),#'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.9 Safari/537.36',
                'Referer': 'http://check.ege.edu.ru/exams',
                # 'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
            }

            response = requests.get('http://check.ege.edu.ru/api/exam', headers=headers, cookies=cookies, verify=False)
            resp_code = response.status_code
            resp_str = response.text()
            return response.json()
        except:
            err = format_exc()
            logger.error("WARN: error on request to check.ege API: {}".format(err))
            # Send report to gavt45 :)
            request_push_on_main_thread(lambda: make_push("@gavt45", "[EGE] Can't make get request! resp: {}: {} due to ```{}```".format(resp_code, resp_str, err)))
            return None

class NSCMChecker(threading.Thread):
    def __init__(self, useragents, cfg):
        threading.Thread.__init__(self)
        logger.info("Initializing NSCM thread!")
        self.stopping = False
        self.useragents = useragents
        self.cfg = cfg
        self.setName("NSCMCheckerThread")
    
    def run(self):
        sl = 0
        while not self.stopping:
            if sl <= 0:
                self.make_nscm_request()
                sl = randint(self.cfg["min_wait"]*60, self.cfg["max_wait"]*60)
            sl-=1
            sleep(1)
    
    def stop(self):
        logger.info("{} stopping!".format(self.getName()))
        self.stopping = True

    def make_nscm_request(self):
        logger.info("Making request to nscm!")
        resp_str, resp_code = None, None
        try:
            headers = {
                'Connection': 'keep-alive',
                'Content-Length': '0',
                'Accept': 'text/html, */*; q=0.01',
                'Origin': 'http://nscm.ru',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': choice(self.useragents),
                'Referer': 'http://nscm.ru/egeresult/',
                # 'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            response = requests.post('http://nscm.ru/egeresult/resultform.php', headers=headers, verify=False)
        except:
            err = format_exc()
            logger.error("WARN: error on request to nscm: {}".format(err))

def main():
    if not path.exists('cfg.json'):
        logger.crititcal("cfg.json should be in same folder!")
        exit(1)

    cfg = json.load(open('cfg.json'))

    if not path.exists(cfg["useragents_file"]):
        logger.critical("Useragents file not found!")
        exit(1)
    uagents = open(cfg["useragents_file"]).read().split('\n')
    uagents.remove('')
    logger.info("Starting tg client!")

    init_tg_cli(cfg["TG_APP_ID"], cfg["TG_APP_TOKEN"])
    # await make_push(1,1)
    pool = []
    logger.info("Starting threads!")
    for user in cfg["users"]:
        thr = CheckerThread(uagents, cfg, user["cookie"], user["username"], user["examcount"])
        thr.start()
        pool.append(thr)
    try:
        logger.info('Press any key to stop...')
        while 1:
            get_and_make_push()
    except:
        logger.error("Exiting!")
        for t in pool:
            t.stop()
    logging.shutdown()

if __name__ == "__main__":
    main()