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
    # 타임아웃 시간 120초 지정
    res = requests.post(ZABBIX_URL, data=json.dumps(payload), headers=headers, timeout=120)
    try:
        return res.json()
    except Exception:
        print(f"⚠️ API 응답 파싱 실패 (Status: {res.status_code})")
        return None

# 1. 'dummy-host-' 대상 전체 호스트 ID 조회
print("🔍 삭제할 더미 호스트를 조회 중입니다...")
hosts_res = call_api("host.get", {
    "output": ["hostid", "host"],
    "search": {"host": "dummy-host-"}
})

if not hosts_res or "result" not in hosts_res:
    print("❌ 호스트 목록을 가져오지 못했습니다.")
    exit()

hosts = hosts_res["result"]
total_count = len(hosts)
print(f"총 {total_count}개의 더미 호스트를 발견했습니다.")

if total_count == 0:
    print("⚠️ 삭제할 더미 호스트가 없습니다.")
    exit()

host_ids = [h["hostid"] for h in hosts]

# 2. 100개씩 안전하게 분할 삭제 (웹 서버 타임아웃 방지)
BATCH_SIZE = 100
print(f"🗑️ 100개씩 분할 삭제를 진행합니다 (총 {total_count}개)...")

for i in range(0, total_count, BATCH_SIZE):
    batch = host_ids[i:i + BATCH_SIZE]
    delete_res = call_api("host.delete", batch)

    if delete_res and "result" in delete_res:
        current_progress = min(i + BATCH_SIZE, total_count)
        print(f" Progress: [{current_progress} / {total_count}] 호스트 삭제 진행 중...")
    else:
        print(f"❌ {i+1}~{i+len(batch)} 구간 삭제 중 오류 발생")

print("🎉 모든 더미 호스트가 성공적으로 정리되었습니다!")