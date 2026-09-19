from datetime import datetime,time
import yaml
from .constant import markets_timings
from collections import OrderedDict
market_types = ['OP','CL']

def read_time_from_disk()-> dict:
    with open('dynamic_market_time.yaml','r') as file:
        market_time = yaml.safe_load(file)
    markets_time_disk = {dic['market_name']: {**dic} for dic in market_time }
    return markets_time_disk

dynamic_market_time = dict()
ondisk_dynamic_market_time = read_time_from_disk()

def verify_time(client_name:str,fixed_market_name:str,dynamic_market:bool)->bool:
    print("########################## TIME VERIFICATION ######################")
    fixed_market_time = markets_timings[fixed_market_name]
    for mkt_name,dic in ondisk_dynamic_market_time.items():
        if mkt_name in fixed_market_time.keys():
            dynamic_market_time[mkt_name] = [time(hour=dic['start_time'][0],minute=dic['start_time'][1]),int(dic['days']),time(hour=dic['end_time'][0],minute=dic['end_time'][1])]


    market_names = (OrderedDict.fromkeys(map(lambda name:name[:-2],fixed_market_time.keys())))

    if pre_time_verification(fixed_market_time,market_names):
        print(f"Successfull Fixed Time Verification of Client:{client_name}")
        if dynamic_market:
            print("In Dynamic")
            if pre_time_verification(dynamic_market_time,market_names):
                if  verify_dynamic_market_time(client_name,dynamic_market_time,fixed_market_time,market_names):
                    print(f"Successfull Dynamic+Fixed Time Verification of Client:{client_name}")
                else:
                    print(f"Failure In Verifying Fixed TIme for CLient: {client_name}")
            else:
                print(f"Failure In Verifying Integrity of Dynamic TIme.")            
    else:
        print(f"Failure In Verifying Fixed TIme of CLient: {client_name}")
    print("######################################################################")

def pre_time_verification(market_times:dict,market_names:list)->bool:
    valid = True
    #local check if all times are in increasing order op-s<op-e<cl-s<cl-e
    for market_name in market_names:
        if not (market_times[market_name+'OP'][0]<market_times[market_name+'OP'][-1]<market_times[market_name+'CL'][0]<market_times[market_name+'CL'][-1]):
            if market_times[market_name+'CL'][-1].hour!=0:
                print(f" ERROR:: {market_name} Interrupting Times (NOt in Increasing Order) ")
                valid =  False
    if valid:
        return True
    else:
        return False

def verify_dynamic_market_time(client_name:str,dynamic_time:dict,fixed_market_time:dict,market_names:list)->bool:
    #checks intersecting times between dynamic and fixed 
    valid = True
    for market_name in market_names:
        for market_type in market_types :
            if (dynamic_time[market_name+market_type][-1] < fixed_market_time[market_name+market_type][-1]):
                print(f" ERROR:: {market_name} Interrupting Times  Dynamic< Fixed ")
                valid = False

            time_diff = (datetime.combine(datetime.today().date(),dynamic_time[market_name+market_type][-1]) - datetime.combine(datetime.today().date(),fixed_market_time[market_name+market_type][-1])).total_seconds()/60
            if time_diff>15:
                print(f"Error TOO MUCH DELAY FROM FIXED Dynamic TIme of {market_name} {market_type} -> {dynamic_time[market_name+market_type][-1]} ")
                valid = False
                #dynamic_time[market_name+market_type][-1] = (datetime.combine(datetime.today(),fixed_market_time[market_name+market_type])[-1] + timedelta(minutes=5)).time()

        # if len([t for t in [dynamic_time[market_name+'CL'][0],fixed_market_time[market_name+'CL'][0]] if t>dynamic_time[market_name+'OP'][-1]]) !=2 :
        #     print(f" ERROR:: {market_name} Confliction in Close Start Times ")
        #     valid = False

    if valid:
        return True
    else:
        return False
        


    