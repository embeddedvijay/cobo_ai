##########################################################################################
    #                  				MESSAGES
##########################################################################################
cancel_strings = ["❌","❌ ❌","❌ ❌ ❌","CANCEL"]
wrong_cancel_format_reply = ""
no_market_name_reply = "*❌❌ Market Name? *"
step_marker_interval = 25
invalid_format_reply = "*Pls Check MSG*"
##########################################################################################
    #                  				MARKETS
##########################################################################################
import datetime
markets_timings = {
    "vijay2" : {
    #(01:00:00)
    "SRIDEVI_DAY_OP" : (datetime.time(1,0,0), 6, datetime.time(11,40,0)),
    "SRIDEVI_DAY_CL" : (datetime.time(11,52,0), 6, datetime.time(12,40,0)),

    "TIME_BAZAR_DAY_OP" : (datetime.time(1,0,0), 5, datetime.time(13,6,0)),
    "TIME_BAZAR_DAY_CL" : (datetime.time(13,18,0), 5, datetime.time(14,6,0)),
    
    "MADHUR_DAY_OP" : (datetime.time(1,0,0), 6, datetime.time(13,33,0)),
    "MADHUR_DAY_CL" : (datetime.time(13,42,0), 6, datetime.time(14,33,0)),

    "RAJDHANI_DAY_OP" : (datetime.time(1,0,0), 5, datetime.time(15,10,0)),
    "RAJDHANI_DAY_CL" : (datetime.time(15,18,0), 5, datetime.time(17,10,0)),

    "MILAN_DAY_OP" : (datetime.time(1,0,0), 5, datetime.time(15,7,0)),
    "MILAN_DAY_CL" : (datetime.time(15,17,0), 5, datetime.time(17,7,0)),
    
    "SUPREME_DAY_OP" : (datetime.time(1,0,0), 6, datetime.time(15,44,0)),
    "SUPREME_DAY_CL" : (datetime.time(15,53,0), 6, datetime.time(17,44,0)),
    
    "KALYAN_DAY_OP" : (datetime.time(1,0,0), 5, datetime.time(15,59,0)),
    "KALYAN_DAY_CL" : (datetime.time(16,18,0), 5, datetime.time(17,59,0)),
    
    ##########################################################################################
    #         START-TIME                WORKING-DAYS             MARKET-END-TIME
    ##########################################################################################
    #(18:00:00)
    "SRIDEVI_NIGHT_OP" : (datetime.time(17,0,0), 6, datetime.time(19,20,0)),
    "SRIDEVI_NIGHT_CL" : (datetime.time(19,32,0), 6, datetime.time(20,20,0)),
    
    "MADHUR_NIGHT_OP" : (datetime.time(17,0,0), 5, datetime.time(20,40,0)),
    "MADHUR_NIGHT_CL" : (datetime.time(20,43,0), 5, datetime.time(22,40,0)),
    
#18#
    "SUPREME_NIGHT_OP" : (datetime.time(17,45,0), 6, datetime.time(20,59,0)),
    "SUPREME_NIGHT_CL" : (datetime.time(21,2,0), 6, datetime.time(22,59,0)),
    
    "MILAN_NIGHT_OP" : (datetime.time(17,45,0), 5, datetime.time(21,12,0)),
    "MILAN_NIGHT_CL" : (datetime.time(21,19,0), 5, datetime.time(23,12,0)),
    
    "RAJDHANI_NIGHT_OP" : (datetime.time(17,45,0), 4,  datetime.time(21,40,0)),
    "RAJDHANI_NIGHT_CL" : (datetime.time(21,44,0), 4,  datetime.time(23,52,0)),
    
    
    "KALYAN_NIGHT_OP" : (datetime.time(18,0,0), 4, datetime.time(21,42,0)),
    "KALYAN_NIGHT_CL" : (datetime.time(21,45,0), 4, datetime.time(23,42,0)),

    "MAIN_BAZAR_NIGHT_OP" : (datetime.time(1,0,0), 4, datetime.time(21,59,0)),
    "MAIN_BAZAR_NIGHT_CL" : (datetime.time(22,2,0), 4, datetime.time(23,59,0)),
    },

    "vijay3":{

    "SRIDEVI_DAY_OP" : (datetime.time(1,0,0), 6, datetime.time(11,39,0)),
    "SRIDEVI_DAY_CL" : (datetime.time(11,44,0), 6, datetime.time(12,39,0)),

    "TIME_BAZAR_DAY_OP" : (datetime.time(1,0,0), 5, datetime.time(13,17,0)),
    "TIME_BAZAR_DAY_CL" : (datetime.time(13,23,0), 5, datetime.time(14,17,0)),
    
    "MADHUR_DAY_OP" : (datetime.time(1,0,0), 6, datetime.time(13,35,0)),
    "MADHUR_DAY_CL" : (datetime.time(13,41,0), 6, datetime.time(14,35,0)),

    "RAJDHANI_DAY_OP" : (datetime.time(1,0,0), 5, datetime.time(15,9,0)),
    "RAJDHANI_DAY_CL" : (datetime.time(15,15,0), 5, datetime.time(17,9,0)),

    "MILAN_DAY_OP" : (datetime.time(1,0,0), 5, datetime.time(15,17,0)),
    "MILAN_DAY_CL" : (datetime.time(15,25,0), 5, datetime.time(16,17,0)),


    "SUPREME_DAY_OP" : (datetime.time(1,0,0), 6, datetime.time(15,36,0)),
    "SUPREME_DAY_CL" : (datetime.time(15,41,0), 6, datetime.time(17,36,0)),

    "KALYAN_DAY_OP" : (datetime.time(1,0,0), 5, datetime.time(16,17,0)),
    "KALYAN_DAY_CL" : (datetime.time(16,25,0), 5, datetime.time(18,17,0)),
    ##########################################################################################
    #         START-TIME                WORKING-DAYS             MARKET-END-TIME
    ##########################################################################################
    #(18:00:00)
    "SRIDEVI_NIGHT_OP" : (datetime.time(17,45,0), 6, datetime.time(19,18,0)),
    "SRIDEVI_NIGHT_CL" : (datetime.time(19,22,0), 6, datetime.time(20,18,0)),

    "MADHUR_NIGHT_OP" : (datetime.time(17,45,0), 5, datetime.time(20,33,0)),
    "MADHUR_NIGHT_CL" : (datetime.time(20,39,0), 5, datetime.time(22,33,0)),
#18#
    "SUPREME_NIGHT_OP" : (datetime.time(17,45,0), 6, datetime.time(20,47,0)),
    "SUPREME_NIGHT_CL" : (datetime.time(20,54,0), 6, datetime.time(22,47,0)),

    "MILAN_NIGHT_OP" : (datetime.time(17,45,0), 5, datetime.time(21,17,0)),
    "MILAN_NIGHT_CL" : (datetime.time(21,22,0), 5, datetime.time(23,17,0)),

    "RAJDHANI_NIGHT_OP" : (datetime.time(17,45,0), 4,  datetime.time(21,36,0)),
    "RAJDHANI_NIGHT_CL" : (datetime.time(21,42,0), 4,  datetime.time(23,40,0)),
    
    #"KALYAN_NIGHT_OP" : (datetime.time(18,30,0), 4, datetime.time(21,50,0)),
    #"KALYAN_NIGHT_CL" : (datetime.time(21,52,0), 4, datetime.time(23,50,0)),

    "MAIN_BAZAR_NIGHT_OP" : (datetime.time(1,0,0), 4, datetime.time(21,55,0)),
    "MAIN_BAZAR_NIGHT_CL" : (datetime.time(22,1,0), 4, datetime.time(23,55,0))
    },


}

# HIGHLY ORDER SENSITIVE CAN ADD ALTERNATIVES
market_names = {

    "SRIDEVI" : ['*SRIDEVI','SHRED', 'SERI', 'SERIDEBI', 'SHIDEVI', 'SHIDEVI', 'SHIRIDIVE', 'SHREDEVI', 'SHREE', 'SHREE C', 'SHREE DEVI', 'SHREEDEV', 
                 'SHREEDEVEE', 'SHREEDEVI', 'SHREEDEVII', 'SHREEDIVEE', 'SHRI', 'SHRI DEVI', 'SHRIDEEVEE', 'SHRIDEEVEI', 'SHRIDEV', 'SHRIDEVEI', 'SHRIDEVI', 
                 'SHRIDEVINIGJT', 'SHRIDHEVI', 'SIRI', 'SRDIVE', 'SREDEVI', 'SREE DEVI', 'SREEDEVEE', 'SREEDEVI', 'SRI', 'SRI C', 'SRI DEVI', 'SRIDAVI', 
                 'SRIDAVICALOS', 'SRIDAVIDAYOP', 'SRIDEBI', 'SRIDEEVEE', 'SRIDEVEE', 'SRIDEVI', 'SRIDEVI', 'SRIDEVI C', 'SRIDEVI NIGHT OPEN', 'SRIDEVI 🆑', 
                 'SRIDEVI,NIGHT,KOLOJ', 'SRIDEVINIGHT', 'SRIDHAVNIGHT', 'SRIDHEVEE', 'SRIDHEVI','देवी','शिरीदेवी', 'श्री', 'श्री देवी','क्षीदेवी', 'श्री देवी ओपन', 'श्रीदेवी', 'सिरी', 'सिरीदेवी', 'ꜱƦꞮ', 
                 'ꜱƦꞮᴅᴇᴠꞮ', '𝕊ℝ𝕀𝔻𝔼𝕍𝕀','𝐒𝐑𝐈𝐃𝐄𝐕𝐈', '𝕊ℝ𝕀𝔻𝔼𝕍𝕀 ℕ ℂ𝕃𝕆𝕊𝔼','SREDEVI','SHRDIEVI','SIREDIVI','SRLDEVL','SHRIDEVI','SIRDEVI'],

    "TIME_BAZAR" : ['TAIM','TIAM', 'TAIM BAZAAR', 'TAIMBAJAR', 'TAIMBAJARCALOS', 'TAIMBAZAAR', 'TAIMBAZAR', 'TAIMBAZARR', 'TAIMBAZR', 'TAIMBAZRA', 'TAIMCALOS', 'TAIME', 
                    'TAIMEBAZAAR', 'TAIMEBAZAR', 'TEIM', 'TIEM', 'TIIME BAZAR', 'TIMBAZR', 'TIME', 'TIME BAZAARR', 'TIME BAZAR', 'TIME BAZARRE', 'TIMEBAZAAR', 
                    'TIMEBAZAR', 'TIMEBAZRA', 'TIMEBAZROPAN', 'TIMEBAZZAR', 'TIMME BAZAAR', 'TUME', 'TYME BAZAR', 'टाइम ', 'टाइम बजर', 'टाइम बजार', 'टाइम बाज़र', 
                    'टाइम बाज़ार', 'टाइम बाजार', 'टाइमबाजर', 'टाइमबाज़र', 'टाइमबाज़ार', 'टाइमबाज़ारक्लोज', 'टाइमबाजार', 'टाइमबाजारओपन', 'टाइमबाजारक्लोज', 'टाईम ', 'टाईम बजर', 'टाईम बजार', 
                    'टाईम बाज़र', 'टाईम बाज़ार', 'टाईम बाजार', 'टाईमबाजरक्लोज', 'टाईमबाज़ार', 'टाईमबाज़ारक्लोज', 'ᴛꞮᴍᴇ', 'ᴛꞮᴍᴇʙᴀᴢᴀƦ', '𝐓𝐢𝐦𝐞', '𝕋𝕀𝕄𝔼', '𝕋𝕀𝕄𝔼𝔹𝔸ℤ𝔸ℝ'],

    "MADHUR" : ['*MADHUR', 'MADHAR', 'MADHU', 'MADHUR', 'MADHUR 🆑', 'MADHUR,DAY,KOLOJ', 'MADHURBANDH', 'MADHURCLOS', 'MADHURDAY', 'MADHURNIGHT', 'MADHURNT', 
                'MAFHUR', 'मधुर', 'मधुर', 'मधुरडे ', 'मधुरडेओपन', 'मधुरडेक्लोज', 'मधुरनाइट ', 'मधुरनाइटओपन', 'मधुरनाइटक्लोज', 'ᴍᴀᴅʜᴇ', 'ᴍᴀᴅʜᴇᴅᴀY', '𝕄𝔸𝔻ℍ𝕌ℝ', '𝕄𝔸𝔻ℍ𝕌ℝℕ𝕀𝔾ℍ𝕋', 
                '𝕄𝔸𝔻ℍ𝕌ℝ𝔻𝔸𝕐'],
    
    "MILAN" : ['*MILAN','MLIAN', 'MILAM','MILAN', 'MILAN NAGIT', 'MILAN,DAY,KOLOJ', 'MILANA', 'MILANBANDH', 'MILANCLOS', 'MILANDAY', 'MILANNIGHT', 'MILANNT', 'MILANOPEN', 
               'MILLAN', 'MILN', 'MILNNNIGHTCLSE', 'मिलन', 'मिलनडे', 'मिलनडे ओपन', 'मिलनडेक्लोज', 'मिलननाइट', 'मिलननाइटओपन', 'मिलननाइटक्लोज', 'मीलन', 'ᴍꞮʟᴀɴ', '𝕄𝕀𝕃𝔸ℕ', 
               '𝕄𝕀𝕃𝔸ℕ 𝔻𝔸𝕐', '𝕄𝕀𝕃𝔸ℕℕ ', '𝕄𝕀𝕃𝔸ℕℕ𝕀𝔾ℍ𝕋 ', '𝕄𝕀𝕃𝔸ℕ𝔻𝔸𝕐', '𝕄𝕀𝕃𝔸ℕ𝔻𝔸𝕐ℂ𝕃𝕆𝕊𝔼', '𝕄𝕚𝕝𝕒𝕟', '𝕄𝕚𝕝𝕒𝕟𝕟'],

    "RAJDHANI" : ['RAJ','RAJADHANI','RAJDH',"राजधानी",'RAJ,DAY,KOLOJ', 'RAJASTHAN', 'RAJDADHAINIGHT', 'RAJDANIGHT', 'RAJDAY', 'RAJDHANI', 'RAJDHANI,DAY,KOLOJ', 'RAJDHANI,NIGHT,KOLOJ', 
                  'RAJDHANIBANDH', 'RAJDHANIDAY', 'RAJDHANINIGHT', 'RAJDHANINT', 'RAJDHHANI', 'RAJDHNIINKGHT', 'RAJDNNII', 'RAJENDRA', 'RAJHADHANI', 
                  'RAJHADHANI NAGIT', 'RAJHADHANINAGIT', 'RAJHDAN', 'RAJJDANI', 'RAJNIGHT', 'RAJNT', 'RAJU', 'RAJUDAY', 'RAJUNIGHT', 'RAJUNT', 'RJADANI', 
                  'राजधानिनाईट', 'राजधानी', 'राजधानीडे', 'राजधानीडे ओपन', 'राजधानीडेओपन', 'राजधानीडेक्लोज', 'राजधानीनाइट', 'राजधानीनाइटओपन', 'राजधानीनाइटक्लोज', 'ℝ𝔸𝕁𝔻ℍ𝔸ℕ𝕀', 'ℝ𝔸𝕁𝔻ℍ𝔸ℕ𝕀 𝔻𝔸𝕐', 
                  'ℝ𝔸𝕁𝔻ℍ𝔸ℕ𝕀ℕ𝕀𝔾ℍ𝕋 ', 'ℝ𝔸𝕁𝔻ℍ𝔸ℕ𝕀ℕ𝕋', 'ℝ𝔸𝕁𝔻ℍ𝔸ℕ𝕀𝔻𝔸𝕐',"राजधानी नाइट","RAJADANI","RAJDHAN","RAJADANI","RAJSTHANI"],
    
    "SUPREME" : ['*SUPREME', 'SUEPRME', 'SUOREME', 'SUPEMRE', 'SUPER', 'SUPER,DAY,KOLOJ', 'SUPER,NIGHT,KOLOJ', 'SUPERDAY C', 'SUPERMAN', 'SUPERME', 'SUPERMNNIGT', 
                 'SUPERNIGHT', 'SUPREAM', 'SUPREEM', 'SUPREEMDAY', 'SUPREEMN', 'SUPREME', 'SUPREME,DAY,KOLOJ', 'SUPREMEBANDH', 'SUPREMED', 'SUPREMEDAY', 
                 'SUPREMEKLOOS', 'SUPREMENIGHT', 'SUPRIM', 'SUPRMEE', 'शुपर', 'शुपरमी', 'सुपर', 'सुपरिम', 'सुपरिमकोलज', 'सुपरीम', 'सुप्रीम ', 'सुप्रीमडे', 'सुप्रीमडे ', 'सुप्रीमडेक्लोज', 
                 'सुप्रीमनाइट ', 'सुप्रीमनाइटओपन', 'सुप्रीमनाइटक्लोज', 'ꜱᴜᴩƦᴇᴍᴇ', 'ꜱᴜᴩƦᴇᴍᴇᴅ', 'ꜱᴜᴩƦᴇᴍᴇᴅᴀY', '𝕊𝕌ℙℝ𝔼𝕄𝔼', '𝕊𝕌ℙℝ𝔼𝕄𝔼ℕ', '𝕊𝕌ℙℝ𝔼𝕄𝔼ℕ𝕀𝔾ℍ𝕋', '𝕊𝕌ℙℝ𝔼𝕄𝔼ℕ𝕀𝔾ℍ𝕋', '𝕊𝕌ℙℝ𝔼𝕄𝔼ℕ𝕋', 
                 '𝕊𝕌ℙℝ𝔼𝕄𝔼𝔻', '𝕊𝕌ℙℝ𝔼𝕄𝔼𝔻𝔸𝕐','Surpme','SURPME','SURPRISE','SURPNE'],
        
    "KALYAN" : ['KALIYAN','KALLUDAY', 'KALIYAAN','KO','KC','KNO','KNC','KAYLA','KD','KDO','KDC','KLYAN','KALLUNIGHT C', 'KALLYAN', 'KALYAANCLSE', 'KALYAANIGHTT', 'KALYAN', 'KALYAN,DAY,KOLOJ', 'KALYAN,KOLOJ', 'KALYAN,NAIT,OPN', 
                'KALYAN,NIGHT,KOLOJ', 'KALYANAM', 'KALYANBAZAR', 'KALYANCL', 'KALYANCLO', 'KALYANJODIII', 'KALYANNIGHT', 'KALYANNIGHT C', 'KALYANNIGT', 
                'KALYANNNIGHY', 'KALYANOPEN', 'KALYN', 'KALYNI', 'KALYNN', 'KLAYAN', 'KLYAANIGHTCLOSS', 'कल्याण', 'कल्याणडे ', 'कल्याणडेओपन', 'कल्याणडेक्लोज', 'कल्याणनाइट', 
                'कल्याणनाइटओपन', 'कल्याणनाइटक्लोज', 'ᴋᴀʟYᴀɴ', 'ᴋᴀʟYᴀɴᴄʟᴏꜱᴇ', '𝕂𝔸𝕃𝕐𝔸ℕ', '𝕂𝔸𝕃𝕐𝔸ℕℕ', '𝕂𝔸𝕃𝕐𝔸ℕℕ𝕀𝔾ℍ𝕋', '𝕂𝔸𝕃𝕐𝔸ℕℕ𝕀𝔾ℍ𝕋 ', '𝕂𝔸𝕃𝕐𝔸ℕℕ𝕋', '𝕂𝔸𝕃𝕐𝔸ℕℕ𝕋 ', '𝕂𝔸𝕃𝕐𝔸ℕ𝔻', 
                '𝕂𝔸𝕃𝕐𝔸ℕ𝔻ℂ𝕃𝕆𝕊𝔼', '𝕂𝔸𝕃𝕐𝔸ℕ𝔻𝔸𝕐ℂ','KALAYAN','KN','KALYAM','KALYM','KAL'],
    
    "MAIN_BAZAR" : ['*MAIN', 'MAIN', 'MAIN,KOLOJ', 'MAINBAZAAR', 'MAINE', 'MAN', 'MANBAZAR', 'MANE', 'MEIN', 'MEINBAZAR', 'MEN', 'MENBAZAR JODI', 'MIAN', 'मेन', 
                    'मेनबाजार', 'मेनबाजारओपन', 'मेनबाजारक्लोज', 'ᴍᴀꞮɴ', 'ᴍᴀꞮɴ ʙᴀᴊᴀƦ', 'ᴍᴀꞮɴʙ', '𝕄𝔸𝕀ℕ', '𝕄𝔸𝕀ℕ𝔹', '𝕄𝔸𝕀ℕ𝔹ℂ𝕃𝕆𝕊𝔼', '𝕄𝔸𝕀ℕ𝔹𝔸ℤ𝔸ℝ', '𝕄𝔸𝕀ℕ𝔹𝔸ℤ𝔸ℝℂ', '𝕄𝔸𝕀ℕ𝔹𝔸ℤ𝔸ℝℂ𝕃𝕆𝕊𝔼', 
                    '𝕄𝕒𝕚𝕟', '𝕄𝕒𝕚𝕟𝕓', '𝕄𝕒𝕚𝕟𝕓𝕒𝕫𝕒𝕣','MINBAJR','MAIM'],

}
all_market_names = sorted([x for values in list(market_names.values()) for x in list(set(values))],key=lambda x: len(x),reverse=True)

#TOALAL

sethFixedNameTiming = {
    "SRIDEVI_DAY_OP" : datetime.time(11, 40),
    "SRIDEVI_DAY_CL" : datetime.time(12, 40),

    "SUPREME_DAY_OP" : datetime.time(15, 39),
    "SUPREME_DAY_CL" : datetime.time(17, 39),

    "SRIDEVI_NIGHT_OP" : datetime.time(19, 20),
    "SRIDEVI_NIGHT_CL" : datetime.time(20, 20),

    "SUPREME_NIGHT_OP" : datetime.time(20, 49),
    "SUPREME_NIGHT_CL" : datetime.time(22, 49),
}

'''
daynamic time = true
SRIDEVI_DAY_OP = 11.40
SRIDEVI_DAY_CL = 12.40
SUPREME_DAY_OP = 15.39
SUPREME_DAY_CL = 17.39
SRIDEVI_NIGHT_OP = 19.20
SRIDEVI_NIGHT_CL = 20.20
SUPREME_NIGHT_OP = 20.49
SUPREME_NIGHT_CL = 22.49

markets_timings = {
    "vijay" : {
    #(01:00:00)

    "SRIDEVI_DAY_OP" : (datetime.time(1,0,0), 6, datetime.time(11,32,0)),
    "SRIDEVI_DAY_CL" : (datetime.time(11,42,0), 6, datetime.time(12,32,0)),


    "SUPREME_DAY_OP" : (datetime.time(1,0,0), 6, datetime.time(15,33,0)),
    "SUPREME_DAY_CL" : (datetime.time(15,41,0), 6, datetime.time(17,33,0)),


    ##########################################################################################
    #         START-TIME                WORKING-DAYS             MARKET-END-TIME
    ##########################################################################################
    #(18:00:00)
    "SRIDEVI_NIGHT_OP" : (datetime.time(17,45,0), 6, datetime.time(19,12,0)),
    "SRIDEVI_NIGHT_CL" : (datetime.time(19,22,0), 6, datetime.time(20,12,0)),


#18#
    "SUPREME_NIGHT_OP" : (datetime.time(17,45,0), 6, datetime.time(20,41,0)),
    "SUPREME_NIGHT_CL" : (datetime.time(20,51,0), 6, datetime.time(22,41,0)),
    },
'''