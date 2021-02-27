import requests
import json
import string
import steam.webauth as wa
import re
import time

# TODO save state, and do so securely -- cookies, confirmed redeemed keys, etc

# Humble endpoints
loginpage = "https://www.humblebundle.com/login"
loginurl = "https://www.humblebundle.com/processlogin"
redeemurl = "https://www.humblebundle.com/humbler/redeemkey"

# May actually be able to do without these, but for now they're in.
usefulheaders = {"Content-Type":"application/x-www-form-urlencoded", "Accept": "application/json, text/javascript, */*; q=0.01"}

def login(session):
    authorized = False
    while authorized == False:
        username = input("Email:")
        password = input("Password:")
        csrfreq = session.get(loginpage)

        payload={"access_token":"","access_token_provider_id":"","goto":"/","qs":"","username":username,"password":password}
        usefulheaders["CSRF-Prevention-Token"] = csrfreq.cookies['csrf_cookie']

        r = session.post(loginurl,data=payload,headers=usefulheaders)
        loginjson = r.json()
        if("errors" in loginjson):
            print(loginjson['errors'])
            exit()
        else:
            twofactored = False
            while not twofactored:
                # There may be differences for Humble's SMS 2FA, haven't tested.
                if("humble_guard_required" in loginjson):
                    humble_guard_code = input("Please enter the Humble security code: ")
                    payload['guard'] = humble_guard_code.upper() # Humble security codes are case-sensitive via API, but luckily it's all uppercase!
                    auth = session.post(loginurl,data=payload,headers=usefulheaders)
                    authjson = auth.json()
                    
                    if('user_terms_opt_in_data' in authjson and authjson['user_terms_opt_in_data']['needs_to_opt_in']):
                        # Nope, not messing with this.
                        print("There's been an update to the TOS, please sign in to Humble on your browser.")
                        exit()
                    if(auth.status_code == 200):
                        twofactored = True
                elif(auth.status_code == 401):
                    print("Sorry, your two-factor isn't supported yet.")
                    exit()

            return True

def redeem_humble_key(sess,tpk):
    # Keys need to be 'redeemed' on Humble first before the Humble API gives the user a Steam key.
    # This triggers that for a given Humble key entry
    payload = {'keytype': tpk['machine_name'],'key':tpk['gamekey'],'keyindex':tpk['keyindex']}
    resp = sess.post(redeemurl,data=payload,headers=usefulheaders)
    if(resp.status_code != 200 or not resp.json()['success']):
        print("Error redeeming key on Humble Bundle for " + tpk['human_name'])
        return ""
    return resp.json()['key']

def _redeem_steam(session,key):
    # Based on https://gist.github.com/snipplets/2156576c2754f8a4c9b43ccb674d5a5d
    if key == "":
        return 0
    sessionID = session.cookies.get_dict()["sessionid"]
    r = session.post('https://store.steampowered.com/account/ajaxregisterkey/',data={'product_key':key,'sessionid':sessionID})
    blob = r.json()

    if blob["success"] == 1:
        for item in blob["purchase_receipt_info"]["line_items"]:
            print("Redeemed " + item["line_item_description"])
        return 0
    else:
        errorCode = blob["purchase_result_details"]
        sErrorMessage = ""
        if errorCode == 14:
            sErrorMessage = 'The product code you\'ve entered is not valid. Please double check to see if you\'ve mistyped your key. I, L, and 1 can look alike, as can V and Y, and 0 and O.'
        elif errorCode == 15:
            sErrorMessage = 'The product code you\'ve entered has already been activated by a different Steam account. This code cannot be used again. Please contact the retailer or online seller where the code was purchased for assistance.'
        elif errorCode == 53:
            sErrorMessage = 'There have been too many recent activation attempts from this account or Internet address. Please wait and try your product code again later.'
        elif errorCode == 13:
            sErrorMessage = 'Sorry, but this product is not available for purchase in this country. Your product key has not been redeemed.'
        elif errorCode == 9:
            sErrorMessage = 'This Steam account already owns the product(s) contained in this offer. To access them, visit your library in the Steam client.'
        elif errorCode == 24:
            sErrorMessage = 'The product code you\'ve entered requires ownership of another product before activation.\n\nIf you are trying to activate an expansion pack or downloadable content, please first activate the original game, then activate this additional content.'
        elif errorCode == 36:
            sErrorMessage = 'The product code you have entered requires that you first play this game on the PlayStation®3 system before it can be registered.\n\nPlease:\n\n- Start this game on your PlayStation®3 system\n\n- Link your Steam account to your PlayStation®3 Network account\n\n- Connect to Steam while playing this game on the PlayStation®3 system\n\n- Register this product code through Steam.'
        elif errorCode == 50: 
            sErrorMessage = 'The code you have entered is from a Steam Gift Card or Steam Wallet Code. Browse here: https://store.steampowered.com/account/redeemwalletcode to redeem it.'
        else:
            sErrorMessage = 'An unexpected error has occurred.  Your product code has not been redeemed.  Please wait 30 minutes and try redeeming the code again.  If the problem persists, please contact <a href="https://help.steampowered.com/en/wizard/HelpWithCDKey">Steam Support</a> for further assistance.'
        
        print(sErrorMessage)
        return errorCode

def redeem_steam_keys(humble_session,humble_keys):
    # Sign into Steam web
    s_username = input("Steam Username:")
    user = wa.WebAuth(s_username)
    session = user.cli_login()

    print("Signed in. Getting your owned content to avoid attempting to register keys already owned...")

    # Query owned App IDs according to Steam
    ownedcontent = session.get("https://store.steampowered.com/dynamicstore/userdata/").json()
    ownedgames = ownedcontent['rgOwnedPackages'] + ownedcontent['rgOwnedApps']

    # Some Steam keys come back with no Steam AppID from HB
    # So we do our best to look up from AppIDs (no packages, because can't find an API for it)
    pattern = re.compile('[\W_]+')
    steam_app_list = {pattern.sub('',app['name']).lower():app['appid'] for app in session.get("https://api.steampowered.com/ISteamApps/GetAppList/v2/").json()['applist']['apps']}
    for idx, game in enumerate(humble_keys):
        if game['steam_app_id'] == None:
            human_name = pattern.sub('',game['human_name'].lower())
            if(human_name in steam_app_list):
                humble_keys[idx]['steam_app_id'] = steam_app_list[human_name]

    # This is filtering out any keys that don't end up with a steam AppID because it suited me more
    # Will want to prompt the user to ask them most likely
    unownedgames = [key for key in humble_keys if key['steam_app_id'] != None and key['steam_app_id'] not in ownedgames]
    undeterminedgames = [key for key in humble_keys if key['steam_app_id'] == None]

    #ownedgames = [key for key in humble_keys if key not in unownedgames]

    print("Filtered out game keys that is certified you already own on Steam; {unowned} keys unowned, and {undetermined} couldn't be determined to a Steam AppID".format(unowned=len(unownedgames),undetermined=len(undeterminedgames)))

    for key in unownedgames:
        print(key['human_name'])
        redeemed_key = ""
        if('redeemed_key_val' not in key):
            # This key is unredeemed via Humble, trigger redemption process.
            redeemed_key = redeem_humble_key(humble_session,key)
        else:
            redeemed_key = key['redeemed_key_val']
        while _redeem_steam(session,redeemed_key) == 53:
            # Steam seems to limit to about 50 keys/hr -- even if all 50 keys are legitimate *sigh*
            # Duplication counts towards Steam's rate limit, hence why we've worked so hard above to figure out what we already own
            print("Waiting an hour for rate limit to go away...")
            time.sleep(60*60)

# Create a consistent session for Humble API use
session = requests.Session()
login(session)
print("Successfully logged in.")

orders = session.get("https://www.humblebundle.com/api/v1/user/order").json()
print("Getting {} order details, please wait".format(len(orders)))

# TODO: multithread this
order_details = [session.get("https://www.humblebundle.com/api/v1/order/" + order['gamekey'] + "?all_tpkds=true").json() for order in orders]

unredeemed_keys = []
redeemed_keys = []
steam_keys = []
for game in order_details:
    if 'tpkd_dict' in game and 'all_tpks' in game['tpkd_dict']:
        steam_keys.extend([tpk for tpk in game['tpkd_dict']['all_tpks'] if tpk['key_type_human_name'] == 'Steam'])

for key in steam_keys:
    if 'redeemed_key_val' in key:
        redeemed_keys.append(key)
    else:
        # Has not been redeemed via Humble yet
        unredeemed_keys.append(key)

print("{keycnt} Steam keys -- {redeemedcnt} redeemed, {unredeemedcnt} unredeemed".format(keycnt=len(steam_keys),redeemedcnt=len(redeemed_keys),unredeemedcnt=len(unredeemed_keys)))

# TODO: Prompt the user for their preferences on redeeming on Steam all keys or subsets(redeemed, unredeemed, ambiguous, etc)

redeem_steam_keys(session,steam_keys)