from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from .db_ops import get_client_table,get_contact_cutting,get_result_of_market,get_client_contacts,get_business_date
from datetime import datetime,timedelta
from .hla_adv.constants.number import main_num_list
import datetime as dtt
from .config import get_contacts,get_contacts_table
from .debug_log import trace


import builtins
original_print = builtins.print
def print(*args, **kwargs):
    kwargs['flush'] = True
    original_print(*args, **kwargs)

class Scheduler:

    def _dynamic_end_time(self, market, end_time):
        """Move a table job to its configured post-close grace end."""
        config = self.dynamic_timing or {}
        markets = config.get("markets", {}) or {}
        rule = markets.get(market, {}) or {}
        enabled = bool(rule.get("enabled", rule.get("status", False)))
        if not rule and not markets:
            rule = config
            enabled = bool(config.get("status", False))
        minutes = int(rule.get("minutes", 0) or 0)
        if not enabled or minutes <= 0:
            return end_time
        return (datetime.combine(dtt.date.today(), end_time) + timedelta(minutes=minutes)).time()

    def _schedule_days(self, market, start_time, end_time):
        """Return calendar weekdays for a market's table job.

        Desktop weekdays describe the market day. For a close that ends after
        midnight, its cron job runs on the following calendar day. Business
        date remains separate and is still governed by the 04:00 rollover.
        Configurations without explicit weekdays preserve legacy every-day
        behaviour.
        """
        selected = (self.session_data.get("market_days") or {}).get(market)
        if not isinstance(selected, (list, tuple, set)):
            return "*"
        try:
            days = sorted({int(day) % 7 for day in selected})
        except (TypeError, ValueError):
            return "*"
        if not days:
            return "*"
        if end_time <= start_time:
            days = sorted({(day + 1) % 7 for day in days})
        return ",".join(str(day) for day in days)

    def _add_market_job(self, market, start_time, run_time, target, per):
        days = self._schedule_days(market, start_time, run_time)
        self.scheduler.add_job(
            self.send_table,
            trigger=CronTrigger(year="*", month="*", day="*", day_of_week=days,
                                hour=run_time.hour, minute=run_time.minute, second=run_time.second),
            args=[self.client_name, market, target, per],
            misfire_grace_time=60, coalesce=True,
        )
        trace(f"[SCHEDULER] registered market={market} at={run_time.isoformat()} weekdays={days} target={target!r}")
        if '_CL' in market:
            check_time = (datetime.combine(dtt.date.today(), run_time) - timedelta(minutes=10)).time()
            self.scheduler.add_job(
                self.check_open_result_of_market,
                trigger=CronTrigger(year="*", month="*", day="*", day_of_week=days,
                                    hour=check_time.hour, minute=check_time.minute, second=check_time.second),
                args=[market], misfire_grace_time=60, coalesce=True,
            )
            trace(f"[SCHEDULER] registered open-result check market={market} at={check_time.isoformat()} weekdays={days}")

    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler()
        trace(f"[SCHEDULER] init client={self.client_name} table_routes={bool(self.out_contacts.get('table', False))} markets={len(self.markets_time)}")
        if self.out_contacts.get('table', False):
            for timings in (self.markets_time, self.dynamic_market_time):
                for market, (start, _day_count, market_time) in timings.items():
                    target = self.out_contacts['table'].get(market)
                    if not target:
                        continue
                    per = self.out_contacts['table'].get(market + 'per', 100)
                    self._add_market_job(market, start, self._dynamic_end_time(market, market_time), target, per)

        self.scheduler.start()
        trace(f"[SCHEDULER] started client={self.client_name} jobs={len(self.scheduler.get_jobs())}")
        return

    def check_open_result_of_market(self,market:str):
        market_result = get_result_of_market(market=market[:-3])
        if market_result:
            return
        #self.send_message_to("My Airtel",f"No Open Result found for Market {market[:-3]}\n Please ADD under 10 Minutes..")

    def send_table_legacy(self,client_name,market,master_contact,per = 100, customer_contacts=None)->bool:
        """Original conversion-based table builder retained for reference only.

        Scheduler jobs call the new send_table() below. Do not delete this
        legacy version: it documents the earlier OP/CL Jodi/Sangam behavior.
        """
        # Director creates one table per output group. A customer contributes
        # only to the group selected for this market, never to another group's
        # table. Recursive calls reuse the original legacy table formatter.
        routes = self.table_routes_for_market(market)
        if customer_contacts is None and routes:
            sent = False
            for target, contacts in routes.items():
                sent = self.send_table_legacy(client_name, market, target, per, customer_contacts=contacts) or sent
            return sent

        customers = list(customer_contacts or self.customer_contacts)
        data = {key:0 for key in main_num_list}

        contact_cutting = get_contact_cutting(client_name=self.client_name)
        for contact in customers:
            contact_per = contact_cutting.get(contact,100)/100
            cdata = get_client_table(client_name,market,contact_name=contact,to_settle=True)
            for k,v in cdata.items():
                if k in list(data.keys()):
                    data[k] +=int(int(v)*contact_per)
                else:
                    data[k] = int(int(v)*contact_per)
        #data = get_client_table(client_name,market,to_settle=True)
        # Keep the settlement payload in the same shape as the WhatsApp table.
        # It is created after OP/CL conversion below, not here.
        market_name = market
        if(("TIME" in market) or ("MAIN" in market)):
            if("DAY" in market):
                market_name = market_name.replace("DAY","")
            else:
                market_name = market_name.replace("NIGHT","")

        msg_table = f"*{market_name}*\n"
        msg_table_panna = f"*{market_name}*\n"

        sum = 0
        panna_sum = 0
        close_jodi = ''
        if '_OP' in market:
            jodis = []
            for val,price in data.items():
                if len(val)==2 and price>0:
                    initital_amt = int(data.get(val[0],0))
                    data[val[0]] = initital_amt + int(price)
                    jodis.append(val)
                elif '-' in val and price>0:
                    _in_op = val.split('-')[0]
                    initital_amt = int(data.get(_in_op,0))
                    data[_in_op] = initital_amt + int(price)
                    jodis.append(val)
            for val in jodis:
                del data[val]

        elif '_CL' in market:
            data_open = {key:0 for key in main_num_list}
            for contact in customers:
                contact_per = contact_cutting.get(contact,100)/100
                odata_setteled = get_client_table(client_name,market.replace('CL','OP'),contact_name=contact,to_settle=False,settled=True,c_settled=False,to_csettle=True)
                for k,v in odata_setteled.items():
                    if(k in list(data_open.keys())):
                        data_open[k] +=int(int(v)*contact_per)
                    else:
                        data_open[k] = int(int(v)*contact_per)
                odata = get_client_table(client_name,market.replace('CL','OP'),contact_name=contact,to_settle=False,settled=False,c_settled=False,to_csettle=True)
                for k,v in odata.items():
                    if(k in list(data_open.keys())):
                        data_open[k] +=int(int(v)*contact_per)
                    else:
                        data_open[k] = int(int(v)*contact_per)

            try:
                open = get_result_of_market(market[:-3])["OPEN"]
                openPanal = get_result_of_market(market[:-3])["OPANAL"]
                for val,price in data_open.items():
                    if len(val)==2 and val[0]==open and price>0:
                        initital_amt = int(data.get(val[1],0))
                        data[val[1]] = initital_amt + int(price*10)
                        close_jodi += f' {val} @ {price} \n'
                    elif '-' in val and price>0:
                        _in_op = val.split('-')[0]
                        _in_cl = val.split('-')[1]
                        if(_in_op == open):
                            initital_amt = int(data.get(_in_op,0))
                            data[_in_cl] += (initital_amt + int(price * 10))
                            close_jodi += f'Sangam {val} @ {price} \n'
                        elif(_in_op == openPanal):
                            _panal_prices = {1:600,2:300,3:150}
                            initital_amt = int(data.get(_in_op,0))
                            data[_in_cl] += initital_amt + int(price * _panal_prices[len(set([x for x in _in_op ]))])
                            close_jodi += f'Sangam {val} @ {price} \n'
            except:
                ####################### backup code delte after trail ##########
                for open in [str(x) for x in range(0,10)]:
                    close_jodi += f'\n\n IF OPEN ANK => {open} \n'
                    for val,price in data_open.items():
                        if len(val)==2 and val[0]==open and price>0:
                            initital_amt = int(data.get(val[1],0))
                            #data[val[1]] = initital_amt + int(price*10)
                            close_jodi += f'\t{val[1]} @ {str(int(price * 10))} \n'

                print("NO OPEN Result DURING CLOSE SETTelment")
        for val,price in data.items():
            # if ((len(val)==3) and (price > 70)):
            #     panna_sum += price-70
            #     msg_table_panna += f"*{val}={price-70}*\n"
            if(price>0):
                sum += price
                msg_table += f"*{val}={price}*\n"
                

        msg_table += f"*TOTAL={sum}*"
        print(f"\t{market} Result {client_name}->{master_contact}\n{msg_table}")
        
        if(sum>0):
            # For CL, open-jodi/sangam values may have been converted into
            # close numbers. Snapshot the final outgoing table, otherwise the
            # final quoted reply can falsely say NO WIN.
            settlement_bets = {str(key): int(value) for key, value in data.items() if int(value) > 0}
            self.send_message_to(
                master_contact, msg_table, market=market,
                settlement_payload={"bets": settlement_bets, "total_play": sum},
                # A due table must outrank periodic outbox flushing and normal
                # acknowledgements. Sending remains sequential per WhatsApp
                # account, so this changes ordering without parallel sends.
                priority=100, business_date=get_business_date(),
            )
            if close_jodi:
                #self.send_message_to("My New",close_jodi)
                pass

        # self.send_table_web(client_name,market,master_contact,per)
        return True

    def send_table(self, client_name, market, master_contact, per=100, customer_contacts=None) -> bool:
        """New direct DB table: customer LD cut, but never game conversion.

        `45=120` with LD 70 is therefore sent as `45=84` for both OP and CL.
        Original game keys, including Jodi and Sangam keys, remain untouched.
        """
        routes = self.table_routes_for_market(market)
        trace(f"[SCHEDULER] fire client={client_name} market={market} requested_target={master_contact!r} routes={routes!r}")
        if customer_contacts is None and routes:
            sent = False
            for target, contacts in routes.items():
                sent = self.send_table(client_name, market, target, per, customer_contacts=contacts) or sent
            return sent

        customers = list(customer_contacts or self.customer_contacts)
        data = {}
        contact_cutting = get_contact_cutting(client_name=self.client_name)
        for contact in customers:
            contact_per = contact_cutting.get(contact, 100) / 100
            rule = self.rule_for(contact)
            ld = self._whole_amount(rule.get("LD", 100))
            overflow_limits = (rule.get("overflow_limits", {}) or {}) if ld == 100 else None
            if overflow_limits and str(overflow_limits.get("output_group") or "").strip():
                trace(f"[SCHEDULER] overflow base-only contact={contact} market={market} limits={overflow_limits!r}")
            # This is the same DB read/settle point as the old function. Only
            # the OP/CL number conversion below it has been removed. For a
            # 100% LD overflow customer it also excludes the excess that was
            # already sent instantly to the separate overflow group.
            cdata = get_client_table(client_name, market, contact_name=contact, to_settle=True,
                                     overflow_limits=overflow_limits, overflow_ld=ld)
            for key, value in cdata.items():
                amount = int(int(value) * contact_per)
                if amount:
                    data[str(key)] = data.get(str(key), 0) + amount

        market_name = market
        if ("TIME" in market) or ("MAIN" in market):
            market_name = market_name.replace("DAY", "") if "DAY" in market else market_name.replace("NIGHT", "")
        # WhatsApp table order is intentional: Ank 0-9, Jodi 00-99, then
        # Panna 000-999.  Keep the original DB keys and amounts untouched.
        def table_sort_key(item):
            key = str(item[0]).strip()
            return (len(key), int(key), key) if key.isdigit() else (99, 0, key)

        rows = sorted(
            ((key, amount) for key, amount in data.items() if amount > 0),
            key=table_sort_key,
        )
        total = sum(amount for _key, amount in rows)
        trace(f"[SCHEDULER] table client={client_name} market={market} target={master_contact!r} customers={customers!r} rows={rows!r} total={total}")
        message = "\n".join([f"*{market_name}*", *[f"*{key}={amount}*" for key, amount in rows], f"*TOTAL={total}*"])
        print(f"\t{market} Direct DB {client_name}->{master_contact}\n{message}")
        if total > 0:
            self.send_message_to(
                master_contact, message, market=market,
                settlement_payload={"bets": dict(rows), "total_play": total},
                priority=100, business_date=get_business_date(),
            )
        return True
    
    def send_table_web(self,client_name,market,master_contact,per = 100)->bool:

        for master_contact,customer_contacts in get_contacts_table(client_name).items():
            print(master_contact,"==========>>",customer_contacts)
            data = {key:0 for key in main_num_list}

            contact_cutting = {k:int(100-int(v.get("LD",0))) for k,v in get_contacts(client_name).items()}
            for contact in customer_contacts:
                contact_per = contact_cutting.get(contact,100)/100
                cdata = get_client_table(client_name,market,contact_name=contact,to_settle=False,settled=True)
                for k,v in cdata.items():
                    data[k] +=int(int(v)*contact_per)
            #data = get_client_table(client_name,market,to_settle=True)
            market_name = market
            if(("TIME" in market) or ("MAIN" in market)):
                if("DAY" in market):
                    market_name = market_name.replace("DAY","")
                else:
                    market_name = market_name.replace("NIGHT","")

            msg_table = f"*{market_name}*\n"
            msg_table_panna = f"*{market_name}*\n"

            sum = 0
            panna_sum = 0
            close_jodi = ''
            if '_CL' in market:
                data_open = {key:0 for key in main_num_list}
                for contact in customer_contacts:
                    contact_per = contact_cutting.get(contact,100)/100
                    odata_setteled = get_client_table(client_name,market.replace('CL','OP'),contact_name=contact,to_settle=False,settled=True,c_settled=True)
                    for k,v in odata_setteled.items():
                        data_open[k] +=int(int(v)*contact_per)
                    odata = get_client_table(client_name,market.replace('CL','OP'),contact_name=contact,to_settle=False,settled=False,c_settled=True)
                    for k,v in odata.items():
                        data_open[k] +=int(int(v)*contact_per)

                try:
                    open = get_result_of_market(market[:-3])["OPEN"]
                    for val,price in data_open.items():
                        if len(val)==2 and val[0]==open and price>0:
                            initital_amt = int(data.get(val[1],0))
                            data[val[1]] = initital_amt + int(price*10)
                            close_jodi += f' {val} @ {price} \n'
                except:
                    ####################### backup code delte after trail ##########
                    for open in [str(x) for x in range(0,10)]:
                        close_jodi += f'\n\n IF OPEN ANK => {open} \n'
                        for val,price in data_open.items():
                            if len(val)==2 and val[0]==open and price>0:
                                initital_amt = int(data.get(val[1],0))
                                #data[val[1]] = initital_amt + int(price*10)
                                close_jodi += f'\t{val[1]} @ {str(int(price * 10))} \n'

                    print("NO OPEN Result DURING CLOSE SETTelment")
            for val,price in data.items():
                if ((len(val)==3) and (price > 70)):
                    panna_sum += price-70
                    msg_table_panna += f"*{val}={price-70}*\n"
                elif(price>0):
                    sum += price
                    msg_table += f"*{val}={price}*\n"
                    

            msg_table += f"*TOTAL={sum}*"
            msg_table_panna += f"*TOTAL={panna_sum}*"
            print(f"\t{market} Result WEb {client_name}->{master_contact}\n{msg_table}")
            
            if(sum>0):
                return True
                self.send_message_to(self.out_contacts['table'][market],msg_table)
                self.send_message_to(self.out_contacts['table'][market],msg_table_panna)
                if close_jodi:
                    self.send_message_to("My New",close_jodi)


        return True
    
    def show_jobs(self)->None:
        for job in self.scheduler.get_jobs():
          print(job)
