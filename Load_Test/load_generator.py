import sys, threading, time, random, subprocess

# 사용법: python3 load_generator_dist.py [START_ID] [END_ID]
# 예시: python3 load_generator_dist.py 1 500

if len(sys.argv) < 3:
    print("Usage: python3 load_generator_dist.py <START_HOST_ID> <END_HOST_ID>")
    sys.exit(1)

START_ID = int(sys.argv[1])
END_ID = int(sys.argv[2])
TOTAL_HOSTS = END_ID - START_ID + 1

# Zabbix Proxy Group 공인 IP 리스트
PROXY_IPS = ["1.201.178.7", "1.201.178.35"]
TARGET_PORT = "10051"
INTERVAL = 10  # 10초 주기

def send_metrics_for_host(host_id):
    host_name = f"dummy-host-{host_id:04d}"

    while True:
        cpu_val = round(random.uniform(10.0, 85.0), 2)
        mem_val = round(random.uniform(30.0, 90.0), 2)

        lines = [
            f"{host_name} system.cpu.util {cpu_val}",
            f"{host_name} vm.memory.util {mem_val}"
        ]

        # Dummy Trapper Template의 dummy.metric.01 ~ 23 메트릭 생성 (총 25개)
        for k in range(1, 24):
            val = round(random.uniform(1.0, 100.0), 2)
            lines.append(f"{host_name} dummy.metric.{k:02d} {val}")

        payload = "\n".join(lines) + "\n"

        # Proxy Group 순회: 리다이렉트 발생 시 담당 프록시(failed: 0)를 만날 때까지 전송
        for proxy_ip in PROXY_IPS:
            cmd = ["zabbix_sender", "-z", proxy_ip, "-p", TARGET_PORT, "-i", "-"]
            res = subprocess.run(
                cmd,
                input=payload,  # text=True 환경에 맞춰 문자열(str)로 전달
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 담당 프록시에서 성공 응답(failed: 0)을 받으면 루프 탈출
            if "processed:" in res.stdout and "failed: 0" in res.stdout:
                break

        time.sleep(INTERVAL)

print(f"Starting metric generator for hosts {START_ID} to {END_ID} ({TOTAL_HOSTS} hosts)...", flush=True)

delay = INTERVAL / TOTAL_HOSTS

for i in range(START_ID, END_ID + 1):
    t = threading.Thread(target=send_metrics_for_host, args=(i,))
    t.daemon = True
    t.start()
    time.sleep(delay)

print(f"All {TOTAL_HOSTS} generators active on this node!", flush=True)

while True:
    time.sleep(10)