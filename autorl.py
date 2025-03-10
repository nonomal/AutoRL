import requests
import json
import datetime
import socket

prefix = "https://api.cloudflare.com/client/v4/"

## BEGIN CONFIGURATION
CF_EMAIL = ""
CF_AUTH_KEY = ""
DEFAULT_MODE = "block"

ACCESS_LOG_PATH = "/var/log/nginx/access.log"
INTERVAL_MIN = 1
RATE_PER_MINUTE = 600

TG_CHAT_ID = ""
TG_BOT_TOKEN = ""

IP_WHITE_LIST = ["1.1.1.1"]
## END CONFIGURATION

def get_existing_rules():
    path = "user/firewall/access_rules/rules?per_page=10"
    header = {
        "X-Auth-Email": CF_EMAIL,
        "X-Auth-Key": CF_AUTH_KEY,
        "Content-Type": "application/json"
    }
    r = requests.get(prefix + path, headers=header)
    total_pages = r.json()['result_info']['total_pages']
    rules = []
    for page in range(1, total_pages + 1):
        path = "user/firewall/access_rules/rules?per_page=1000&page=" + str(page)
        r = requests.get(prefix + path, headers=header)
        rules += r.json()['result']
    return rules

def add_ip_to_block_rule(ip_addr, domain):
    path = "user/firewall/access_rules/rules"
    header = {
        "X-Auth-Email": CF_EMAIL,
        "X-Auth-Key": CF_AUTH_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "mode": DEFAULT_MODE,
        "configuration": {
            "target": "ip",
            "value": ip_addr
        },
        "notes": "Auto blocked by AutoRL on " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " for " + domain
    }
    r = requests.post(prefix + path, headers=header, data=json.dumps(data))
    return r.json()

def remove_ip_from_block_rule(ip_addr):
    existing_rules = get_existing_rules()
    for rule in existing_rules['result']:
        if rule['configuration']['value'] == ip_addr:
            path = "user/firewall/access_rules/rules/" + rule['id']
            header = {
                "X-Auth-Email": CF_EMAIL,
                "X-Auth-Key": CF_AUTH_KEY,
                "Content-Type": "application/json"
            }
            r = requests.delete(prefix + path, headers=header)
            return r.json()

def parse_nginx_log(log_path):
    with open(log_path, 'r') as f:
        lines = f.readlines()
    
    # NGINX format is 2022-04-30T20:15:18+08:00
    datetime_format = "%Y-%m-%dT%H:%M:%S+08:00"

    ip_addr_counter = {}
    ip_domain_counter = {}
    for line in lines:
        ip_addr = line.rsplit(' ', 1)[1].strip().replace('"', '')
        log_datetime = datetime.datetime.strptime(line.split(' ')[1], datetime_format)
        requested_domain = line.split(' ')[5].strip()
        if (datetime.datetime.now() - log_datetime).total_seconds() / 60 < INTERVAL_MIN:
            if "-" in ip_addr or ip_addr in IP_WHITE_LIST:
                continue
            else:
                if ip_addr not in ip_addr_counter:
                    ip_addr_counter[ip_addr] = 1
                else:
                    ip_addr_counter[ip_addr] += 1
        
            if ip_addr not in ip_domain_counter:
                ip_domain_counter[ip_addr] = {}
            if requested_domain not in ip_domain_counter[ip_addr]:
                ip_domain_counter[ip_addr][requested_domain] = 1
            else:
                ip_domain_counter[ip_addr][requested_domain] += 1
    return ip_addr_counter, ip_domain_counter

def get_bad_ips(ip_addr_counter,ip_domain_counter):
    bad_ip_list = []
    bad_ip_visit_count = []
    bad_ip_visited_top_domain = []
    for ip_addr, count in ip_addr_counter.items():
        if count > RATE_PER_MINUTE:
            bad_ip_list.append(ip_addr)
            bad_ip_visit_count.append(count)

            bad_ip_domain_list = ip_domain_counter[ip_addr]
            bad_ip_visited_top_domain.append(max(bad_ip_domain_list, key=bad_ip_domain_list.get))

    return bad_ip_list, bad_ip_visit_count, bad_ip_visited_top_domain

def send_message_to_telegram(chat_id, text):
    url = "https://api.telegram.org/bot" + TG_BOT_TOKEN + "/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text
    }
    r = requests.post(url, data=data)
    return r.json()

if __name__ == '__main__':
    ip_addr_counter, ip_domain_counter = parse_nginx_log(ACCESS_LOG_PATH)
    bad_ip_list, bad_ip_visit_count, bad_ip_visited_top_domain = get_bad_ips(ip_addr_counter,ip_domain_counter)
    for i in range(len(bad_ip_list)):
        msg = "On Host: " + socket.gethostname() + ", with IP " + bad_ip_list[i] + " has accessed domain " + str(bad_ip_visited_top_domain[i]) + " for " + str(bad_ip_visit_count[i]) + " times in the last " + str(INTERVAL_MIN) + " minutes, now blocked."
        add_ip_to_block_rule(bad_ip_list[i], bad_ip_visited_top_domain[i])
        if TG_CHAT_ID != "":
            send_message_to_telegram(TG_CHAT_ID, msg)