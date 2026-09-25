from .constant import markets_timings,market_names,all_market_names,sethFixedNameTiming,invalid_format_reply
from .db_ops import add_data,cancel_check,get_client_play,get_client_win,get_client_contacts,get_sequential_client_messages
# from hla_beta import hla_calculate
# from time_manager import write_time
from datetime import datetime,timedelta
import json
from fuzzywuzzy import fuzz
import traceback
import re

# from .hla_adv import adv_run as HLA
# from .hla_adv import adv_run as hla_calculate
from .hla_adv import hla
hla_calculate = hla(debug=False).run

from .dynamic_handler import dynamic_validator,format_conversion
from .debug_log import trace

#HLA = hla(debug=False).run


import builtins
original_print = builtins.print
def print(*args, **kwargs):
    kwargs['flush'] = True
    original_print(*args, **kwargs)


def f_match(input_str, str_list):
    max_ratio = 80
    matched_str = False
    for str_item in str_list:
        ratio = fuzz.ratio(input_str, str_item)
        if ratio > max_ratio:
            max_ratio = ratio
            matched_str = True
    return matched_str

def format_check(msg:str,client_name=""):
    MARKET = False
    #expr = rf"[a-zA-Z]+|/-|[^\W\d_][\u0900-\u097F]*|\S"
    #string = re.findall(expr,msg)
    string = re.findall(r'[a-zA-Z]+|\b[ऀ-ॿ]+\b',msg)
    mkt_list = list()
    for s in string:
        # while(len(s)>5):
        #     s = s[:-1]
        for mkt,names in market_names.items():
            if((s.upper() in names) or (f_match(s.upper(),names))):
                mkt_list.append(mkt)
                break
    if(len(set(mkt_list)) == 1):
        MARKET = mkt_list[0]
        # number = re.findall(r'\d+',msg)
        # if((len(number)>1)):
        return MARKET
        # else:
        #     return False
 ############################### FOR SETH #########################
    elif client_name == "seth"  :
        number = re.findall(r'\d+',msg)
        if((len(number)>1)):
            current_time = datetime.now().time()
            for mktName,timeLimit in sethFixedNameTiming.items():
                if current_time <= timeLimit:
                    return mktName
        return False
 ################################################################

    else:
        return False


def set_active_market(active_market:dict,markets_time:dict)->dict:
    for market_time,marekt_list in active_market.items(): 
        temp_markets = list()
        for market_name,(start,work_day,end) in markets_time.items():
            if((datetime.now().weekday() <= work_day) and (market_time in market_name)):
                temp_markets.append(market_name[:-3])
            elif datetime.now().time().hour <1 and (datetime.now().weekday() <= work_day+1) and (market_time in market_name):
                temp_markets.append(market_name[:-3])
            temp_markets = list(dict.fromkeys(temp_markets))
        active_market[market_time] = temp_markets
    print(f"Todays Active Markets ; {active_market}")
    return active_market


class Reply_processor:

    def __init__(self) -> None:
        # Desktop dynamic timing is a fixed post-close grace window. Do not
        # load/mutate the old YAML result-driven manager, which could move a
        # configured market close unexpectedly.
        self.dynamic_market_time = {}
        self.active_market = set_active_market({
                                    "DAY" : list(),
                                    "NIGHT" : list()},self.markets_time)
        return

    def _dynamic_rule(self, market: str) -> dict:
        config = self.dynamic_timing or {}
        markets = config.get("markets", {}) or {}
        row = markets.get(market, {}) or {}
        if row:
            rule = {**config, **row}
            rule["enabled"] = bool(row.get("enabled", row.get("status", False)))
            return rule
        if not markets and config.get("status", False):
            return {**config, "enabled": True}
        return {"enabled": False}

    def _market_day_enabled(self, market: str, day, work_day: int) -> bool:
        selected = (self.session_data.get("market_days") or {}).get(market)
        if isinstance(selected, (list, tuple, set)):
            try:
                return day.weekday() in {int(value) % 7 for value in selected}
            except (TypeError, ValueError):
                return False
        return day.weekday() <= int(work_day)

    def _is_dynamic_grace(self, market: str, now: datetime | None = None) -> bool:
        rule = self._dynamic_rule(market)
        minutes = int(rule.get("minutes", 0) or 0)
        if not rule.get("enabled") or minutes <= 0 or market not in self.markets_time:
            return False
        now = now or datetime.now()
        start_time, work_day, end_time = self.markets_time[market]
        end_at = datetime.combine(now.date(), end_time)
        market_day = end_at.date()
        if end_time <= start_time:
            market_day -= timedelta(days=1)
        elapsed = (now - end_at).total_seconds()
        return 0 <= elapsed <= minutes * 60 and self._market_day_enabled(market, market_day, work_day)

    def get_active_market(self,market:str):
        current = datetime.now()
        current_time = current.time()
        active_markets = []
        for market_name, (start_time,work_day,end_time) in self.markets_time.items():
            if start_time < end_time:
                if start_time <= current_time < end_time and self._market_day_enabled(market_name, current.date(), work_day):
                    active_markets.append(market_name)
            else:
                if start_time <= current_time or current_time < end_time:
                    market_day = current.date() if current_time >= start_time else (current - timedelta(days=1)).date()
                    if self._market_day_enabled(market_name, market_day, work_day):
                        active_markets.append(market_name)
            if self._is_dynamic_grace(market_name, current):
                active_markets.append(market_name)
        for name in active_markets:
            if market.upper() in name:
                return name
        return False
    
    def reply_image(self,contact:str,message_id:str,image_path:str,text:str):
        msg = ""
        data = dict()
        data["Client"] = self.client_name
        data["Contact"] = contact
        data["Message"] = text
        data["Message_ID"] = message_id
        data["Image"] = True
        data["Action"] = "Image ✅✅"
        add_data(data)
        if self.out_contacts['fast_forward'].get('image',False):
            msg += "✅✅"
            text_with_image = text
            self.send_image_to(self.out_contacts['fast_forward']['image'],image_path,text_with_image)
        return msg,0


    def reply(self,text:str,contact:str,message_id:str):
        market = format_check(text,self.client_name)
        #print("what is market name..",market)
        if(not market and (contact!=self.play_win_trigger) and (contact!=self.testing)):
            return "",0
        elif(market and (contact!=self.play_win_trigger)):
            data = dict()
            # market time check
            data["Client"] = self.client_name
            data["Contact"] = contact
            data["Time"] = datetime.now().time().strftime('%H:%M:%S')
            data["Message"] = text
            data["Message_ID"] = message_id

            if(contact in ["Ansh_PANA"]):
                data["Forwarded"] = True
                self.send_message_to("All_game",text)
                add_data(data)
                return '',0

            if self.client_name == "seth" and any(x in market for x in ['_OP','_CL']) :
                pass
            else:
                market = self.get_active_market(market)

            if(market and (contact != self.testing) and (contact != self.play_win_trigger)):
                msg = ''
                data["Market"] = market
                #return "",0 # need to remove
                try:
                    action,result_list,total,hla_analysis,flag = hla_calculate(text,market = market) 
                except:
                    action = "✅✅"
                    hla_analysis = {"hla_failure" : True }
                    flag = ''
                    result_list = False

                # The operator can independently silence only these three
                # acknowledgement classes. Errors/cancel notices continue to
                # be delivered so the sender is never left without feedback.
                normal_accepted = action.startswith("✅") and action not in ("✅✅", "✅🔴")
                self.last_reply_type = (
                    "total_ok" if flag == "amt" else
                    "fast_forward_ok" if action == "✅✅" else
                    "normal_ok" if normal_accepted else None
                )
                rule = self.rule_for(contact)
                trace(
                    f"[PLAY TRACE] contact={contact} market={market} action={action!r} flag={flag!r} "
                    f"result={result_list!r} total={locals().get('total')!r} "
                    f"ld={rule.get('LD', 100)!r} instant={self.is_instant_cutting(contact)} "
                    f"overflow={rule.get('overflow_limits', {})!r}",
                )

                
                if('CL' in market):
                    msg += "*CLOSE*"
                current_time = datetime.now().time()

                text += f'\n {contact}'

                if action == "✅✅":
                    if (flag == 'amt') or (hla_analysis.get("Sangam",False)):
                        pass
                    else:              
                        msg += '  '+invalid_format_reply            
                        data["Action"] = msg
                        data["Analysis"] = hla_analysis
                        add_data(data)
                        return msg,1

                if(flag == 'amt'):
                    if self._is_dynamic_grace(market) and not dynamic_validator(self._dynamic_rule(market), result_list, total):
                        data["Action"] = "❌ Dynamic limit"
                        data["Analysis"] = hla_analysis
                        data['dynamic_validation'] = False
                        add_data(data)
                        return "❌",1
                    msg += "✅✅"
                    # A missing/wrong total can still contain fully parsed
                    # game rows. LD=100 category overflow is independent of
                    # the acknowledgement type, so do not lose its instant
                    # excess route because this branch returns early.
                    overflow_sent = self.send_category_overflow(contact, market, result_list)
                    # Instant Cutting never forwards raw source text. It must
                    # still send the calculated LD table when the HLA asks
                    # the customer to use/confirm its calculated total.
                    if self.is_instant_cutting(contact):
                        instant_sent = self.send_instant_table(contact, market, result_list)
                        trace(f"[PLAY TRACE] total_check delivery overflow_sent={overflow_sent} instant_sent={instant_sent}")
                    else:
                        # Parsed total-check plays are never Fast Forward.
                        # They wait for their normal scheduler/final flow;
                        # an overflow table, when present, is the only
                        # immediate derived output.
                        trace(f"[PLAY TRACE] total_check raw_forward_suppressed parsed=True overflow_sent={overflow_sent}")
                    return msg,1
                
                elif( action == "✅✅"):
                    if self._is_dynamic_grace(market):
                        data["Action"] = "❌ Dynamic format/limit"
                        data["Analysis"] = hla_analysis
                        data['dynamic_validation'] = False
                        add_data(data)
                        return "❌",1
                    msg += action
                    self.forward_unparsed(contact, market, text)
                    return msg,1
                
                if self._is_dynamic_grace(market):
                    dynamic_rule = self._dynamic_rule(market)
                    if action == "✅🔴":
                        data["Action"] = "❌ Time Over"
                        msg = "❌"
                        data['dynamic_validation'] = False
                        add_data(data)
                        return "LAST TIME CANCEL NAHI HOGA",1
                    if normal_accepted and dynamic_validator(dynamic_rule, result_list, total):
                        data["Action"] = action
                        data["Result"] = result_list
                        data["Total"] = total
                        instant = self.is_instant_cutting(contact)
                        data["Settled"] = instant
                        data["Analysis"] = hla_analysis
                        data['dynamic_validation'] = True
                        msg += action
                        add_data(data)
                        self.notify_limit_once(contact)
                        instant_sent = self.send_instant_table(contact, market, result_list) if instant else False
                        overflow_sent = self.send_category_overflow(contact, market, result_list)
                        trace(f"[PLAY TRACE] dynamic delivery forwarded=False instant_sent={instant_sent} overflow_sent={overflow_sent}")
                        return msg,1
                    data["Action"] = "❌ Dynamic limit"
                    data["Analysis"] = hla_analysis
                    data['dynamic_validation'] = False
                    add_data(data)
                    return "❌",1
                    
                # elif (current_time > self.markets_time[market][-1]  or  current_time <= self.markets_time[market][0] )  and (self.markets_time[market][-1].hour!=0) :
                #     data["Action"] = "❌ Time Over"
                #     add_data(data)
                #     return "❌",0 

                    
                # HLA returns a plain ✅ for some formats and
                # `✅ *Total = N*` for others. Both are accepted plays and
                # must enter the exact same forwarding/instant/overflow path.
                elif normal_accepted:
                    msg += action
                    data["Result"] = result_list
                    data["Total"] = total
                    data["Action"] = msg
                    # Instant groups are recorded as already table-sent so the
                    # end-time scheduler cannot send their amount again.
                    instant = self.is_instant_cutting(contact)
                    data["Settled"] = instant
                    data["Analysis"] = hla_analysis
                    add_data(data)
                    self.notify_limit_once(contact)
                    instant_sent = self.send_instant_table(contact, market, result_list) if instant else False
                    overflow_sent = self.send_category_overflow(contact, market, result_list)
                    # Valid parsed plays stay in the legacy scheduler path.
                    # Only the explicit ✅✅ (unparsed fast-forward) branch
                    # above may send raw customer text to Forward.
                    trace(f"[PLAY TRACE] accepted delivery forwarded=False instant_sent={instant_sent} overflow_sent={overflow_sent}")
                    return msg,0
                
                elif(action == "✅🔴"):
                    cancel = cancel_check(result_list,market,self.client_name,contact_name=contact)
                    if(not cancel):
                        data["Action"] = "❌ Invalid Transaction" + msg
                        data["Analysis"] = hla_analysis
                        add_data(data)
                        msg += "❌"
                        return msg,1
                    else:
                        msg += f"❌"
                        data["Result"] = cancel
                        data["Total"] = -total
                        data["Action"] = msg
                        data["Settled"] = False
                        data["Analysis"] = hla_analysis
                        add_data(data)
                        return msg,1
                else:
                    msg += action
                    if(action == "❌"):
                        data["Action"] = msg
                        data["Analysis"] = hla_analysis
                    else:
                        data["Result"] = result_list
                        data["Total"] = total
                        data["Action"] = msg
                        data["Settled"] = False
                        data["Analysis"] = hla_analysis
                    add_data(data)
                    return msg,1
                
            elif(contact == self.testing):
                failure = ""
                try:
                    action,result_list,total,hla_analysis,flag = hla_calculate(text)
                except:
                    action = "✅✅"
                    result_list,total = [],[]
                    failure = "FAILURE"
                    flag = ''
                action += f"\n*List*{result_list}\n*Total:{total},{failure}*"

                action.replace("'","")
                return action,0
            else:
                data["Action"] = "❌ Time Over"
                add_data(data)
                return "❌",0 
            
        elif(contact == self.play_win_trigger):
            time = False
            results = re.findall(r'\d{3}-\d{2}-\d{3}',text)
            temp_market = list()
            for market_time,marekt_list in self.active_market.items():
                if(market_time in text):
                    time = market_time
                    temp_market = marekt_list
                else:
                    continue
            if(len(results)==len(temp_market)):
                data = dict()
                data["Market_Result"] = True
                for res in zip(temp_market,results):
                    data[res[0]] ={
                        'OP' : res[1][4:5],
                        'CL' : res[1][5:6],
                        'JODI' : res[1][4:6],
                        'OP_PANAL' : res[1][0:3],
                        'CL_PANAL' : res[1][7:10]
                        }
                if self.client_name == 'vijay':
                    add_data(data)
                if time:
                    print("Triggerd For Play and Win")
                    self.send_play(time)
                    self.send_win(time,data)
                    try:
                        #self.send_sequential_play_of_messages(time)
                        pass
                    except:
                        print("Error in sequ play send")
                        traceback.print_exc()

                        #self.send_disclaimer(time)
            return "",0
        
        else:
            if contact == self.testing:
                return "",0
            data["Contact"] = contact
            data["Time"] = datetime.now().time().strftime('%H:%M:%S')
            data["Message"] = text
            data["Troubleshooting"] = True
            add_data(data)
            print("URGENT:::THIS IS BEING LOST::ISSUE")
            return "",0
            

    def send_play(self,time:str):
        if(self.out_contacts.get('play')):
            grand_total = int(0)
            msg = "\t*PLAY*\t\n"
            for contact in get_client_contacts(self.client_name):
                total = int(0)
                msg += f"{contact}\n"
                for market in self.active_market[time]:
                    for mkt_type in ['_OP','_CL']:
                        play = get_client_play(self.client_name,contact,market+mkt_type)
                        if(play):
                            msg+= f"\t{market+mkt_type}=> {play}\n"
                            total += play
                            grand_total += play
                msg+=f"\tTOTAL:: {total}\n"
            msg+=f"GRAND TOTAL:: {grand_total}"
            print(f"{self.client_name}-->{self.out_contacts['play']}\n{msg}")
            self.send_message_to(self.out_contacts['play'],msg)

    def send_sequential_play_of_messages(self,time:str):
        if(self.out_contacts.get('play')):
            grand_total = int(0)
            msg = "\t*PER MESSAGE PLAY*\t\n"
            for contact in get_client_contacts(self.client_name):
                total = int(0)
                msg += f"\n{contact}\n"
                for market in self.active_market[time]:
                    for mkt_type in ['_OP','_CL']:
                        plays_list = get_sequential_client_messages(self.client_name,contact,market+mkt_type)
                        if(plays_list):
                            msg+= f"\n\t{market+mkt_type}=>"
                            for play in plays_list:
                                if play[-1]>0:
                                    msg += f" +{play[-1]}"
                                else:
                                    msg += f" -{play[-1]}"
                                total += play[-1]
                                grand_total += play[-1]
                msg+=f"\n\tTOTAL:: {total}\n"
            msg+=f"GRAND TOTAL:: {grand_total}"
            print(f"{self.client_name}-->{self.out_contacts['play']}\n{msg}")
            self.send_message_to(self.out_contacts['play'],msg)

    def send_win(self,time:str,result_data:dict):
        if(self.out_contacts.get('win')):
            msg_amt = "\t*WIN AMOUNT*\t\n"
            msg = "\t*WIN*\t\n"
            win_grand_total = 0
            for contact in get_client_contacts(self.client_name):
                msg += f"*{contact}*\n"
                msg_amt += f"*{contact}*\n"
                contact_total_win = 0
                contact_win_overall = {'ank':0,'jodi':0,'sp':0,'dp':0,'tp':0}
                for market in self.active_market[time]:
                    win_name =["OPEN PANAL","OPEN","JODI","CLOSE","CLOSE PANAL"]
                    win = get_client_win(self.client_name,contact,market,result_data)
                    win_amt_res_list = list()
                    if(any(w[1]>0 for w in win)):
                        msg += f"\t{market}\n"
                        #msg_amt += f"\t{market}\n"
                        for i in range(0,5):
                            if(win[i][1]):
                                msg += f"\t\t{win_name[i]} {win[i][0]}==> {win[i][1]}\n"
                                win_amt_res_list.append([str(win[i][0]),int(win[i][1])])

                        win_amt_dict = format_conversion(win_amt_res_list)
                        #return type of win_amt_dict {'ank':dict(amt:res_list),'jodi':dict(),'sp':dict(),'dp':dict(),'tp':dict()}
                        win_amt_multiplier = {'ank':9.5,'jodi':95,'sp':150,'dp':300,'tp':600}
                        #market_total_win = 0
                        for k,v in win_amt_multiplier.items():
                            amt = 0
                            for temp_amt,res in win_amt_dict[k].items():
                                amt += int(temp_amt * len(res) * v)
                            if amt:
                                contact_win_overall[k] += amt
                                #market_total_win += amt
                                #contact_total_win += market_total_win
                                #msg_amt += f"\t\t{k.upper()} ==> {amt}\n"
                        #msg_amt += f"\t\t {market.upper()} Total => {market_total_win}\n"
                for k,v in contact_win_overall.items():
                    if v:
                        msg_amt += f"\t\t{k.upper()} => {v}\n"
                        contact_total_win += v
                msg_amt += f"\t\t {contact} Total ==> {contact_total_win}\n"
                win_grand_total += contact_total_win
            msg_amt += f"\t\t Grand Total ==> {win_grand_total}\n"


            print(f"{self.client_name}-->{self.out_contacts['win']}\n{msg}")
            self.send_message_to(self.out_contacts['win'],msg)
            print(f"{self.client_name}-->{self.out_contacts['win']}\n{msg_amt}")
            self.send_message_to(self.out_contacts['win'],msg_amt)

    def send_sequential_win_of_messages(self,time:str,result_data:dict):
        if(self.out_contacts.get('win')):
            msg = "\t*WIN AMOUNT PER MESSAGE*\t\n"
            win_grand_total = 0
            for contact in get_client_contacts(self.client_name):
                msg += f"*{contact}*\n"
                contact_total_win = 0
                contact_win_overall = {'ank':0,'jodi':0,'sp':0,'dp':0,'tp':0}
                for market in self.active_market[time]:
                    win_map = {"O":result_data[market]["OP"],"J":result_data[market]["JODI"],"C":result_data[market]["CL"],"OP":result_data[market]["OP_PANAL"],"CP":result_data[market]["OP_PANAL"]}
                    for mkt_type in ["_OP","_CL"]:
                        plays_list = get_sequential_client_messages(self.client_name,contact,market+mkt_type)
                        for play in plays_list:
                            win_name = {k:0 for k in ["","SP"]}
                            for sl in play[0]:
                                pass


                    win = get_client_win(self.client_name,contact,market,result_data)
                    win_amt_res_list = list()
                    if(any(w[1]>0 for w in win)):
                        msg += f"\t{market}\n"
                        #msg_amt += f"\t{market}\n"
                        for i in range(0,5):
                            if(win[i][1]):
                                msg += f"\t\t{win_name[i]} {win[i][0]}==> {win[i][1]}\n"
                                win_amt_res_list.append([str(win[i][0]),int(win[i][1])])

                        win_amt_dict = format_conversion(win_amt_res_list)
                        #return type of win_amt_dict {'ank':dict(amt:res_list),'jodi':dict(),'sp':dict(),'dp':dict(),'tp':dict()}
                        win_amt_multiplier = {'ank':9.5,'jodi':95,'sp':150,'dp':300,'tp':600}
                        #market_total_win = 0
                        for k,v in win_amt_multiplier.items():
                            amt = 0
                            for temp_amt,res in win_amt_dict[k].items():
                                amt += int(temp_amt * len(res) * v)
                            if amt:
                                contact_win_overall[k] += amt
                                #market_total_win += amt
                                #contact_total_win += market_total_win
                                #msg_amt += f"\t\t{k.upper()} ==> {amt}\n"
                        #msg_amt += f"\t\t {market.upper()} Total => {market_total_win}\n"
                for k,v in contact_win_overall.items():
                    if v:
                        msg_amt += f"\t\t{k.upper()} => {v}\n"
                        contact_total_win += v
                msg_amt += f"\t\t {contact} Total ==> {contact_total_win}\n"
                win_grand_total += contact_total_win
            msg_amt += f"\t\t Grand Total ==> {win_grand_total}\n"


            print(f"{self.client_name}-->{self.out_contacts['win']}\n{msg}")
            self.send_message_to(self.out_contacts['win'],msg)
            print(f"{self.client_name}-->{self.out_contacts['win']}\n{msg_amt}")
            self.send_message_to(self.out_contacts['win'],msg_amt)

    def send_disclaimer(self,time:str):
        if time == "NIGHT":
            self.send_message_to(self.out_contacts['win'],"*Thanks for your support. Your Demo is completed...*")
            self.send_message_to(self.out_contacts['win'],"*Logout..........*")
