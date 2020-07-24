# -*- coding: utf-8 -*-

import requests
from time import sleep
from random import randint,choice
from traceback import format_exc
import threading
import json
from os import path
from telethon.sync import TelegramClient, events
from bs4 import BeautifulSoup
import asyncio
import queue
import sys
import logging
import logging.handlers

callback_queue = queue.Queue()

FORMAT = '%(asctime)-15s %(thread)d %(threadName)s %(message)s'
logging.basicConfig(format=FORMAT,
                    level=logging.INFO)
logger = logging.getLogger('ege_checker')

try:
    syslog_handler = logging.handlers.SysLogHandler(address = '/dev/log')
    logger.addHandler(syslog_handler)
except:
    logger.critical("Can't log to syslog!!!")

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

def init_tg_cli(TG_APP_ID, TG_APP_TOKEN, session_file_path):
    global client
    # logger.info('PATH: {}/somesess'.format('/'.join( [ e for e in cfg_file.split('/')[:-1] ] ) ))
    client = TelegramClient('{}/somesess'.format(session_file_path + ('/' if not session_file_path.endswith('/') else '')),
                            int(TG_APP_ID),
                            TG_APP_TOKEN,
                            proxy=None)

def request_push_on_main_thread(func_to_call_from_main_thread):
    callback_queue.put(func_to_call_from_main_thread)

def get_and_make_push():
    callback = callback_queue.get() #blocks until an item is available
    make_push(callback[0], callback[1])

def make_push(idd, push):
    global client
    with client:
        logger.info("Making push to {}".format(idd))
        client.send_message(idd, push)

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
                    nonnullcount = 0
                    for exam in res["Result"]["Exams"]:
                        if exam["TestMark"] != 0:
                            nonnullcount += 1
                    logger.error("NON NULL COUNT: {} norm count: {}".format(nonnullcount, self.norm_exam_count))
                    if nonnullcount > self.norm_exam_count:
                        logger.critical("EST PROBITIE")
                        logger.critical("RES: {}".format(res))
                        # self.cfg["norm_exam_count"] += 1
                        self.norm_exam_count = nonnullcount
                        # json.dump(self.cfg, open(cfg_file,'w'))
                        request_push_on_main_thread((self.username, "[ЕГЭ] ПОЯВИЛИСЬ РЕЗЫ!!! (теперь их суммарно: {}): ```{}```".format(nonnullcount, res)))
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
            resp_str = response.text
            return response.json()
        except:
            err = format_exc()
            logger.error("WARN: error on request to check.ege API: {}".format(err))
            # Send report to gavt45 :)
            request_push_on_main_thread(("@gavt45", "[EGE] Can't make get request! resp: {}: {} due to ```{}```".format(resp_code, resp_str, err)))
            return None

class NSCMChecker(threading.Thread):
    def __init__(self, useragents, cfg):
        threading.Thread.__init__(self)
        logger.info("Initializing NSCM thread!")
        self.stopping = False
        self.useragents = useragents
        self.cfg = cfg
        self.available_exams = []
        self.setName("NSCMCheckerThread")
    
    def run(self):
        sl = 0
        while not self.stopping:
            if sl <= 0:
                res = self.make_nscm_request()
                # logger.info("RES: {}".format("Физика" in res))
                if res:
                    html = BeautifulSoup(res,"html.parser")
                    tds = html.find_all("td")
                    for exam_name in self.cfg["exams"]:
                        for tag in tds:
                            if (exam_name in str(tag)) and not ("(ГВЭ)" in str(tag)) and not (exam_name in self.available_exams):
                                logger.critical("NEW results on {}".format(exam_name))
                                try:
                                    for user in self.cfg["users"]:
                                        # logger.info("Pushing {}".format(exam_name))
                                        logger.critical("NEW results on {}".format(exam_name))
                                        msg = "[ЕГЭ] ПОЯВИЛИСЬ РЕЗЫ ПО ЭКЗАМЕНУ \"{}\" на http://nscm.ru/egeresult !!!".format(exam_name)
                                        usr = str(user["username"])
                                        # logger.info("Pushing to {}".format(usr))
                                        request_push_on_main_thread((usr, msg))
                                    self.available_exams.append(exam_name)
                                except:
                                    err = format_exc()
                                    logger.error("Error making push for exam {}: {}".format(exam_name,err))
                sl = randint(self.cfg["min_wait"]*60, self.cfg["max_wait"]*60)
                logger.info("Sleeping for {}".format(float(sl)/60.0))
            sl-=1
            sleep(1)
    
    def stop(self):
        logger.info("{} stopping!".format(self.getName()))
        self.stopping = True

    def make_nscm_request(self):
        logger.info("Making request to nscm!")
        resp_str, resp_code = '', None
        try:
            headers = {
                'Connection': 'keep-alive',
                'Content-Length': '0',
                'Accept': 'text/html, */*; charset=utf-8; q=0.01',
                'Origin': 'http://nscm.ru',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': choice(self.useragents),
                'Referer': 'http://nscm.ru/egeresult/',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            }
            response = requests.post('http://nscm.ru/egeresult/resultform.php', headers=headers, verify=False)
            resp_code = response.status_code
            response.encoding = response.apparent_encoding
            resp_str = response.text
            return resp_str
        except:
            err = format_exc()
            logger.error("WARN: error on request to nscm: code: {} res: {} err: {}".format(resp_code, resp_str[:256], err))
            request_push_on_main_thread(("@gavt45", "[EGE] Can't make get request! resp: {}: {} due to ```{}```".format(resp_code, resp_str[:256], err)))
            return None
def main():
    global cfg_file

    if len(sys.argv) >= 2:
        cfg_file = sys.argv[1]
    else:
        logger.fatal("Usage {} <path to config file>".format(sys.argv[0]))
        exit(1)


    if not path.exists(cfg_file):
        logger.crititcal("cfg.json should be in same folder!")
        exit(1)

    cfg = json.load(open(cfg_file))

    if not path.exists(cfg["useragents_file"]):
        logger.critical("Useragents file not found!")
        exit(1)
    uagents = open(cfg["useragents_file"]).read().split('\n')
    uagents.remove('')
    logger.info("Starting tg client!")

    init_tg_cli(cfg["TG_APP_ID"], cfg["TG_APP_TOKEN"], cfg["session_file_path"])
    # await make_push(1,1)
    pool = []
    logger.info("Starting threads!")
    for user in cfg["users"]:
        thr = CheckerThread(uagents, cfg, user["cookie"], user["username"], user["examcount"])
        thr.start()
        pool.append(thr)
    logger.info("Starting NSCMThread!")
    thr = NSCMChecker(uagents, cfg)
    thr.start()
    pool.append(thr)
    try:
        logger.info('Press any key to stop...')
        while 1:
            get_and_make_push()
            sleep(float(randint(1000,10000))/1000.0)
    except:
        err = format_exc()
        logger.fatal("Exiting! Error: {}".format(err))
        for t in pool:
            t.stop()
    logging.shutdown()

if __name__ == "__main__":
    main()