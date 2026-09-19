import re

import builtins
original_print = builtins.print
def print(*args, **kwargs):
    kwargs['flush'] = True
    original_print(*args, **kwargs)
    
def list_normalization(res_list:list)->list:
    new_list = list()
    for sl in res_list:
        if all(len(x)==len(sl[0]) for x in sl[:-1]):
            new_list.append(sl)
        else:
            nums = {1:list(),2:list(),3:list()}
            for num in sl[:-1]:
                nums[len(num)].append(num)
            for k,v in nums.items():
                if v:
                    v.append(sl[-1])
                    new_list.append(v)
    return new_list
            

def format_conversion(res_list:list)->dict:
    res_list = list_normalization(res_list)

    inside = {'ank':dict(),'jodi':dict(),'sp':dict(),'dp':dict(),'tp':dict()}

    for sl in res_list:
        if len(sl[0]) == 1 or len(sl[0]) ==2:
            if len(sl[0]) == 1:
                num_type = 'ank'
            elif len(sl[0]) ==2 :
                num_type = 'jodi'
            inside[num_type][sl[-1]] = inside[num_type].get(sl[-1],[])
            inside[num_type][sl[-1]].append(sl)
        else:
            director = {1:'tp',2:'dp',3:'sp'}
            for num in sl[:-1]:
                x = len(list(set(re.findall(r'\d',num))))
                inside[director[x]][sl[-1]] = inside[director[x]].get(sl[-1],[])
                inside[director[x]][sl[-1]].append(num)
    return inside

    
def dynamic_validator(parameters:dict,res_list:list,total:int)->bool:
    # parameters{'status': bool, 
    #            'max_total' : int,
    #             'ank': int
    #             'jodi':int,
    #             'sp':int,
    #             'dp':int,
    #             'tp':int
    #             }
    try: inside = format_conversion(res_list)
    except: return False
    verified = True
    for k,v in inside.items():
        if  any(key > parameters[k] for key in list(v.keys())):
            verified = False
            print("false1")
    if total>parameters['max_total']:
        verified = False
        print("false2")
    
    return verified

    

# res_list =  [['128', '137', '146', '236', '245', '290', '380', '470', '489', '560', '579', '678', 50], ['129', '138', '147', '156', '237', '246', '345', '390', '480', '570', '589', '679', 50], ['120', '139', '148', '157', '238', '247', '256', '346', '490', '580', '670', '689', 50], ['444', 40], ['1', 1000], ['22', '45', '89', 100]]
# parameters = {
#     'status': True, 
#     'max_total' : 10000,
#     'ank': 1000,
#     'jodi':100,
#     'sp':50,
#     'dp':100,
#     'tp':40
# }
# total = 3500

# if __name__ == '__main__':
#     print(dynamic_validator(parameters,res_list,total))
