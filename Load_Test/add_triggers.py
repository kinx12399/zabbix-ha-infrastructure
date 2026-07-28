import requests, json

ZABBIX_URL = "http://192.168.20.23/zabbix/api_jsonrpc.php"
AUTH_TOKEN = "c769ae759e8b298861747ba21d87561adfda94f7b54fee6484381dd7ca210a03"
TPL_NAME = "Dummy Trapper Template"

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

# 1. Template ID 조회
print(f"🔍 '{TPL_NAME}' ID 조회 중...")
tpl_res = call_api("template.get", {"filter": {"name": [TPL_NAME]}})
if not tpl_res.get("result"):
    print("❌ 템플릿을 찾을 수 없습니다.")
    exit()

template_id = tpl_res["result"][0]["templateid"]

# 2. 생성할 트리거 목록 정의 (연산 부하 극대화 조합)
triggers_to_create = [
    {
        "description": "High CPU Utilization on {HOST.NAME}",
        "expression": f"last(/{TPL_NAME}/system.cpu.util) > 75",
        "priority": 4 # High
    },
    {
        "description": "High Memory Utilization (5m avg) on {HOST.NAME}",
        "expression": f"avg(/{TPL_NAME}/vm.memory.util, 5m) > 80",
        "priority": 3 # Average
    }
]

# dummy.metric.01 ~ 23 에 대한 트리거 추가
for k in range(1, 24):
    triggers_to_create.append({
        "description": f"Dummy Metric {k:02d} Threshold Exceeded on {{HOST.NAME}}",
        # avg와 last를 조합하여 트리거 연산 부하 유도
        "expression": f"avg(/{TPL_NAME}/dummy.metric.{k:02d}, 3m) > 60 and last(/{TPL_NAME}/dummy.metric.{k:02d}) > 70",
        "priority": 2 # Warning
    })

# 3. 트리거 생성 실행
print(f"🚀 총 {len(triggers_to_create)}개의 트리거를 '{TPL_NAME}'에 추가합니다...")

created_count = 0
for trg in triggers_to_create:
    res = call_api("trigger.create", trg)
    if "error" in res:
        print(f"⚠️ 트리거 생성 패스 (이미 존재할 수 있음): {trg['description']}")
    else:
        created_count += 1

print(f"🎉 성공적으로 {created_count}개 트리거가 템플릿에 추가되었습니다!")
print("👉 2,000개 호스트 × 25개 트리거 = 총 50,000개 트리거 연산이 시작됩니다.")