from datetime import datetime,timedelta,time
import yaml
import copy
import re

def read_time_from_disk()-> dict:
    with open('dynamic_market_time.yaml','r') as file:
        market_time = yaml.safe_load(file)
    markets_time_disk = {dic['market_name']: {**dic} for dic in market_time }
    return markets_time_disk

def write_time_to_disk(ondisk_dynamic_market_time:dict,markets_time:dict)-> None:
    file_t = ''''''

    for i,mkt_name in enumerate(ondisk_dynamic_market_time.keys()):
        #mkt_name = k
        if i%2 ==0:
            file_t +='\n\n'
        date_of_change = ondisk_dynamic_market_time[mkt_name].get('date_of_change',0)
        file_t += f"- market_name : {mkt_name}"
        if markets_time.get(mkt_name,False):
            file_t += f"\n\tdays : {markets_time[mkt_name][1]}"
            file_t += f"\n\tstart_time : [{markets_time[mkt_name][0].hour},{markets_time[mkt_name][0].minute}]"
            file_t += f"\n\tend_time : [{markets_time[mkt_name][2].hour},{markets_time[mkt_name][2].minute}]\n"
        else:
            file_t += f"\n\tdays : {ondisk_dynamic_market_time[mkt_name]['days']}"
            file_t += f"\n\tstart_time : {ondisk_dynamic_market_time[mkt_name]['start_time']}"
            file_t += f"\n\tend_time : {ondisk_dynamic_market_time[mkt_name]['end_time']}\n"

        if date_of_change:
            file_t += f"\tdate_of_change : {date_of_change}\n"

    file_t = file_t.replace('\t','  ')

    file_t += f"\n#Last Modified on {datetime.now()}"

    with open('dynamic_market_time.yaml','w') as file:
        file.write(file_t)

class dynamic_time_manager:

    def __init__(self) -> None:
        self.dynamic_market_time = dict()
        self.ondisk_dynamic_market_time = read_time_from_disk()

        for mkt_name,dic in self.ondisk_dynamic_market_time.items():
            if mkt_name in self.markets_time.keys():
                self.dynamic_market_time[mkt_name] = (time(hour=dic['start_time'][0],minute=dic['start_time'][1]),int(dic['days']),time(hour=dic['end_time'][0],minute=dic['end_time'][1]))


    def write_dynamic_time(self,text:str,market_list:list)-> None:
        active_market = copy.deepcopy(market_list)
        current_time = datetime.now()
        todays_date = int(current_time.strftime('%d'))
        if current_time.hour < 2:
            todays_date = int((datetime.now()-timedelta(hours=24)).strftime('%d'))

        
        def open_market_set_time(market_name:str):
            #           TIME DIFFRENCE TO KEEP IN NEW TIME        #
            open_end_time = current_time - timedelta(minutes=1)   #
            close_start_time = current_time - timedelta(minutes=1)#
            #######################################################

            self.dynamic_market_time[market_name] = self.markets_time[market_name][:2] + (time(open_end_time.hour,open_end_time.minute,0),)
            self.ondisk_dynamic_market_time[market_name]['date_of_change'] = todays_date

            market_name = market_name.replace('_OP','_CL')
            self.dynamic_market_time[market_name] = (time(close_start_time.hour,close_start_time.minute,0),) + self.dynamic_market_time[market_name][1:]

        def close_market_set_time(market_name:str):
            close_end_time = current_time - timedelta(minutes=2)
            ####################################################
            self.dynamic_market_time[market_name] =self.dynamic_market_time[market_name][:2] + (time(close_end_time.hour,close_end_time.minute,0),)
            #self.markets_time[market_name][:2] + (time(close_end_time.hour,close_end_time.minute,0),)
            self.ondisk_dynamic_market_time[market_name]['date_of_change'] = todays_date

        
        close_pattern = r"\d{3}-\d{2}-\d{3}"
        open_pattern = r"\d{3}-\d{1}"


        for line in text.split('\n'):
            if re.findall(close_pattern,line):
                market_name = active_market.pop(0)
                market_name += '_CL'
                time_change = (current_time - datetime.combine(current_time.date(), self.markets_time[market_name][2])).total_seconds()/60
            
                if time_change>0 and time_change < 15 and todays_date!= int(self.ondisk_dynamic_market_time[market_name].get('date_of_change',0)) :
                    close_market_set_time(market_name)

                

            elif re.findall(open_pattern,line):
                market_name = active_market.pop(0)
                market_name += '_OP'
                time_change = (current_time - datetime.combine(current_time.date(), self.markets_time[market_name][2])).total_seconds()/60
            
                if time_change>0 and time_change < 15 and todays_date!= int(self.ondisk_dynamic_market_time[market_name].get('date_of_change',0)) :
                    open_market_set_time(market_name)


        write_time_to_disk(self.ondisk_dynamic_market_time,self.dynamic_market_time)
        return




    

    