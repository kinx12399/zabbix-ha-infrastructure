import requests, json

ZABBIX_URL = "http://192.168.20.23/zabbix/api_jsonrpc.php"
AUTH_TOKEN = "c769ae759e8b298861747ba21d87561adfda94f7b54fee6484381dd7ca210a03"

headers = {'Content-Type': 'application/json-rpc'}

def call_api(method, params):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "auth": AUTH_TOKEN,
        "id": 1
    }
    res = requests.post(ZABBIX_URL, data=json.dumps(payload), headers=headers)
    return res.json()

# 1. 'Dummy Trapper Template' ID 자동 조회
print("🔍 'Dummy Trapper Template' ID 조회 중...")
tpl_res = call_api("template.get", {
    "filter": {"name": ["Dummy Trapper Template"]}
})

if not tpl_res.get("result"):
    print("❌ 'Dummy Trapper Template'을 찾지 못했습니다. 이름을 확인해주세요.")
    exit()

template_id = tpl_res["result"][0]["templateid"]
print(f"✅ Found Template ID: {template_id}")

# 2. 2,000개 호스트 생성 (Trapper 템플릿 연동 & 활성화 상태)
print("🚀 2,000개 더미 호스트 생성을 시작합니다...")

for i in range(1, 2001):
    host_name = f"dummy-host-{i:04d}"
    params = {
        "host": host_name,
        "interfaces": [{"type": 1, "main": 1, "useip": 1, "ip": "127.0.0.1", "dns": "", "port": "10050"}],
        "groups": [{"groupid": "2"}],           # Linux servers 그룹 (기본 ID: 2)
        "monitored_by": 2,                     # 2: Proxy group
        "proxy_groupid": "1",                  # ixcloud-proxy-group ID (기본 ID: 1)
        "templates": [{"templateid": template_id}], # ★ Trapper 템플릿 즉시 연결
        "status": 0                            # ★ 0: Enabled (감시 중)
    }

    res = call_api("host.create", params)

    if "error" in res:
        print(f"❌ Error creating {host_name}: {res['error']}")
        break
    elif i % 200 == 0:
        print(f" Progress: {i} / 2000 hosts created...")

print("🎉 모든 호스트 생성이 완료되었습니다! 이제 분산 부하 테스트를 실행할 준비가 되었습니다.")