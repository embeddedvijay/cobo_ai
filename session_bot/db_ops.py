import pymongo 
import traceback
import datetime
from .hla_adv.constants.number import main_num_list
import time
from bson.objectid import ObjectId
import sys

from .config import send_data, connect_to_cluster, load_runtime_config

def get_business_date(now=None):
    """Dynamic trading-date collection; configured rollover protects Main Bazar.

    Do not leave this as a module-import timestamp: a long-running bot would
    otherwise keep writing tomorrow's daytime records into yesterday's DB.
    """
    now = now or datetime.datetime.now()
    rollover = "01:30"
    try:
        rollover = str(load_runtime_config().get("business_day_rollover", rollover))
        hour, minute = (int(part) for part in rollover.split(":", 1))
        cutover = datetime.time(hour, minute)
    except Exception:
        cutover = datetime.time(1, 30)
    if now.time() < cutover:
        now -= datetime.timedelta(days=1)
    return now.strftime("%y-%m-%d")


date = get_business_date()
myclient = pymongo.MongoClient("mongodb://localhost:27017/")
db_frame = myclient["Market"]
db = db_frame[date]


def _collection():
    global date, db
    active_date = get_business_date()
    if active_date != date:
        date = active_date
        db = db_frame[date]
    return db


################## for contact cutting ############
import yaml

def get_contact_cutting(client_name:str)->dict:
    contact_cutting = {}
    config = load_runtime_config()

    for client in config['clients']:
        if client_name != client['client_name']:
            continue
        for session in client['sessions']:
            for contact in session["in_contacts"]:
                contactData = contact.split('^')
                if len(contactData) > 1:
                    contact_cutting[contactData[0].strip()] = int(contactData[1])
                else:
                    contact_cutting[contactData[0].strip()] = 100
    return contact_cutting
####################################################


################################## Returns Boolean #######################################
def add_data(data:dict):
    try:
        print("==============================================================================",flush= True)

        collection = _collection()
        inserted_id = collection.insert_one(data).inserted_id
        #print(db.find_one({"_id": inserted_id})) 
        data["inserted_id"] = inserted_id
        data["Date"] = get_business_date()
        send_data(data)

        token = '{'
        p = ''
        for name,val in data.items():
            #print(f"{name} : {val}",flush=True)
            p += f"{name} : {val}\n"
            #print(f"{repr(name)} : {repr(val)},{type(val)}")
            if isinstance(val,str):
                token += f'"{name}":"{repr(val)[1:-1]}",'
            elif isinstance(val,ObjectId):
                token += f'"{name}":"{val}",'
            elif isinstance(val,bool):
                token += f'"{name}":{str(val).lower()},'
            else:
                token += f'"{name}":{repr(val).replace("'",'"')},'
        
        print(f"{p}---------------------------------------------------------------------------",flush=True)
        time.sleep(0.05)
        sys.stdout.flush()
        
        token = token[:-1] + '}'
        print(token)
        sys.stdout.flush()
        return True
    except:
        print(f"\n\n Failure to Add Data to DB \n Data \n {data} ")
        traceback.print_exc()
        return False

def cancel_check(result_list:list,market_name:str, client_name:str,contact_name:str):
    present_data = get_client_table(client_name,market_name,contact_name=contact_name)
    check = True
    for sl in result_list:
        if(not all(present_data[n] >= int(sl[-1]) for n in sl[:-1])):
            check = False

    if(check):
        for i in range(len(result_list)):
            result_list[i][-1] = -int(result_list[i][-1])
        return result_list

    return False


################################## Returns Data #######################################

def get_client_table(client_name:str,market_name:str,contact_name = {"$exists":True},settled=False,to_settle= False,c_settled=False,to_csettle=False):

    data = _collection().aggregate([
        {
            "$match":{
                "Client" : client_name,
                "Contact" : contact_name,
                "Market" : market_name,
                "Total" : {"$exists":True},
                "Settled" : settled,
                "CSettled":{"$exists":c_settled}
            }
        },
        {
            "$group":{
                "_id" : 0,
                "Transactions":{
                    "$push" : "$Result"
                },
                "object_ids":{
                    "$push":"$_id"
                },
            }
        },
    ])
    num_dict = {key:int(0) for key in main_num_list}
    for doc in data:
        transactions = doc["Transactions"]
        #print(transactions)
        for sl in transactions:
            for l in sl:
                for n in l[:-1]:
                    if(n in list(num_dict.keys())):
                        num_dict[n] += int(l[-1])
                    else:
                        num_dict[n] = int(l[-1])


        if(to_settle):
            try:
                settle_client_result(doc["object_ids"])
            except:
                print(f"Failure To Settle Data of client_name:{client_name}, market_name:{market_name}")
                traceback.print_exc()
        if(to_csettle):
            try:
                close_market_open_settle(doc["object_ids"])
            except:
                print(f"Failure To CSettle Data of client_name:{client_name}, market_name:{market_name},")
                traceback.print_exc()
    
    return num_dict

def get_client_contacts(client_name:str):
    data = _collection().aggregate([
        {
            "$match": {
                "Client": client_name
            }
        }, 
        {
            "$group": {
                "_id": 0, 
                "Contacts": {
                    "$addToSet": "$Contact"
                }
            }
        }
    ])
    for doc in data:
        return list(doc["Contacts"])
    return []


def get_client_play(client_name:str,contact_name:str,market_name:str):
    data = _collection().aggregate([
        {
            "$match":{
                "Client" : client_name,
                "Contact" : contact_name,
                "Market" : market_name,
                "Total" : {"$exists":True},
            }
        },
        {
            "$group":{
                "_id" : 0,
                "SUM":{
                    "$sum" : "$Total"
                },
            }
        },
    ])
    for doc in data:
        return doc['SUM']
    return 0

def get_client_win(client_name:str,contact_name:str,market_name:str,result:dict):
    
    open_data = get_client_table(client_name,market_name+"_OP",contact_name,settled={"$exists":True})
    open_data_csettled = get_client_table(client_name,market_name+"_OP",contact_name,settled={"$exists":True},c_settled=True)
    for k,v in open_data.items():
        open_data[k] += open_data_csettled[k]
    close_data = get_client_table(client_name,market_name+"_CL",contact_name,settled={"$exists":True})

    output = list()
    if result.get(market_name,False):
        res = result[market_name]
        output.append([res['OP_PANAL'],open_data[res['OP_PANAL']]])
        output.append([res['OP'] , open_data[res['OP']]])
        output.append([res['JODI'], open_data[res['JODI']]])
        output.append([res['CL'] , close_data[res['CL']]])
        output.append([res['CL_PANAL'] , close_data[res['CL_PANAL']]])
        return output
    print("REVIEW::No Market_Result found while in get_client_win ")
    return output

def get_sequential_client_messages(client_name:str,contact_name:str,market_name:str)->list:
    data = _collection().find(
        {
            "Client" : client_name,
            "Contact" : contact_name,
            "Market" : market_name,
            "Total" : {"$exists":True}
        },
    ).sort({"Time":1})
    data_list = []
    for doc in data:
        data_list.append([doc["Result"],doc["Total"]])
    return data_list

def get_message_count(client_name:str,contact:str):
    data = _collection().aggregate([
        {
            "$match":{
                "Client" : client_name,
                "Contact":contact,
                "Action":{"$regex":"✅"}
            }
        },
        {
            "$project":{
                "_id":0,
                "Action":1
            }
        }
    ])
    return len(list(data))

def get_all_message_id(client_name:str,contact={"$exists":True})->set:
    data = _collection().find(
        {
            "Client" : client_name,
            "Contact":contact,
            "Message_ID":{"$exists":True}
        },
        {
            "_id":0,
            "Message_ID":1
        }
    ).sort({"Time":1})
    ids = set()
    for doc in data:
        ids.add(doc['Message_ID'])
    return ids
def get_result_of_market(market:str):
    data  = _collection().find_one({
        "Result" : True,
        market : {"$exists":True}
    })
    if data:
        return data[market]
    return data


################################## Update Data #######################################
def settle_client_result(object_ids:list):
    result = _collection().update_many(
            {
                "_id" : {
                    "$in" : object_ids
                }
            },
            {
                "$set":{
                    "Settled": True
                }
            }
        )

def close_market_open_settle(object_ids:list):
    result = _collection().update_many(
            {
                "_id" : {
                    "$in" : object_ids
                }
            },
            {
                "$set":{
                    "CSettled": True,
                }
            },
            upsert=True
        )
