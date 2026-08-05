# OpenStack 기반 프라이빗 클라우드 아키텍처 설계 보고서

본 보고서는 엔터프라이즈 프라이빗 클라우드 환경에서 안정적이고 확장 가능한 인프라를 구현하기 위한 아키텍처 설계 방향과 핵심 구성 요소, 고가용성 전략을 정리한 문서이다. 각 계층은 독립적으로 운영되면서도 REST API, AMQP, Ceph 및 네트워크 오버레이 기술을 통해 유기적으로 연동되도록 설계하였다.

## 1. 아키텍처 개요 및 핵심 설계 원칙

엔터프라이즈 프라이빗 클라우드의 성공적인 구현을 위해 **마이크로서비스 아키텍처(MSA)** 기반의 계층화 설계를 적용합니다. 각 독립 컴포넌트는 REST API 및 AMQP 메시지 브로커를 통해 유기적으로 통신합니다.

### 주요 설계 원칙

- **제어/데이터 영역의 엄격한 분리:** 제어 영역(Control Plane)과 데이터 영역(Data Plane)을 논리적·물리적으로 분리하여 장애 전파를 방지합니다.
- **Stateless API 및 Stateful 레이어 분리:** Stateless API 서비스는 로드밸런서 후면에 배치하여 수평 확장을 보장하며, Stateful 데이터 레이어는 동기식 클러스터링으로 고가용성을 확보합니다.
- **완전 분리형(Fully-Disaggregated) 모델 채택:**
    - 가동률 및 안정성 확보를 위해 제어, 게이트웨이, 컴퓨팅, 스토리지 전용 물리 노드를 격리 배치하는 완전 분리형 모델 적용.
- **통합 멀티 프로토콜 스토리지 구축:** Ceph 클러스터를 기반으로 가상머신용 블록 스토리지와 AWS S3 표준 API 호환 오브젝트 스토리지(Ceph RGW)를 동시에 제공하여 스토리지 활용도를 극대화합니다.

## 2. 핵심 컴포넌트 아키텍처 및 역할 분석

OpenStack을 구성하는 핵심 모듈은 전용 데이터베이스와 API를 보유하며, 개별 역할이 명확히 분화되어 있습니다.

```
                       ┌──────────────────────────────┐
                       │      Keystone (인증/RBAC)     │
                       └──────────────┬───────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
     ┌─────────┐                 ┌─────────┐                 ┌─────────┐
     │  Nova   │ <──Placement──> │ Neutron │ <───OVN/OVS───> │ Storage │
     │ (Compute)                 │(Network)│                 │(Glance/ │
     └─────────┘                 └─────────┘                 │Cinder/  │
                                                             │Ceph RGW)│
                                                             └─────────┘
```

### 컴포넌트 명칭 및 기능 요약표

| **컴포넌트 명칭** | **주요 서비스 프로세스** | **주요 역할 및 기능** | **통신 방식** |
| --- | --- | --- | --- |
| **Keystone** | `keystone-api` | 사용자/프로젝트 인증, 토큰 발행, RBAC 통제, **S3 Access/Secret Key 관리** | HTTP/REST, DB Direct |
| **Nova** | `nova-api`, `nova-conductor`, `nova-scheduler`, `nova-compute` | VM 라이프사이클 오케스트레이션 및 하이퍼바이저 제어 | REST API, AMQP, DB (via Conductor) |
| **Placement** | `placement-api` | 클러스터 내 모든 자원(vCPU, RAM, Disk, GPU 등)의 현황 추적 | HTTP/REST |
| **Neutron** | `neutron-server`, `ovn-northd` | 가상 네트워크(L2/L3, FIP, Security Group) 구축 및 관리 | REST API, OVSDB Protocol, AMQP |
| **Glance** | `glance-api` | OS 이미지 저장 및 메타데이터 관리 (**Ceph RBD / S3 Backend 연동**) | REST API, Ceph/NFS/S3 Native |
| **Cinder** | `cinder-api`, `cinder-scheduler`, `cinder-volume` | 영구 블록 스토리지 생성, 스냅샷, Attach/Detach 제어 (**Ceph RBD**) | REST API, AMQP, Storage Native Driver |
| **Ceph RGW (신규 추가)** | `radosgw` | **AWS S3 및 Swift API 호환 오브젝트 스토리지 게이트웨이** | HTTP/REST (S3 API), RADOS Native |
| **Horizon** | `apache2 (mod_wsgi)` | 웹 브라우저 기반 관리 GUI 대시보드 | REST API |

## 3. 물리적 노드 토폴로지 및 네트워크 아키텍처

트래픽 간섭 방지 및 성능 최적화를 위해 물리 노드 역할을 4가지 그룹으로 분리하고, Spine-Leaf (Two-Tier) 스위치 아키텍처 기반의 4개 독립 네트워크 Plane을 구축합니다.

### 3.1 물리 노드 역할 구별

1. **Controller Node (최소 3대):** 제어 API, Galera DB, RabbitMQ, OVN Control Plane 구동.
2. **Gateway Node (최소 2대):** 외부 통신(North-South) 및 Floating IP, SNAT 처리 전담.
3. **Compute Node (가변 N대):** KVM 기반 VM 구동, `ovn-controller`, OVS 데이터 플레인 동작.
4. **Storage Node (최소 3대):** Ceph 분산 스토리지 클러스터로 구성되어 블록 및 RADOS Gateway로 데이터 영구 저장.

### 3.2 네트워크 Plane

| **Network Plane (구분)** | **주요 트래픽** | **트래픽 성격** | **분리 명분** |
| --- | --- | --- | --- |
| **Management Network** | OpenStack API 통신, 제어 메시지큐, SSH 관리 접속 등 | 용량은 작지만 지연 시간에 매우 민감하며, 핵심 제어 통신에 해당 | 트래픽이 폭증해도 OpenStack 클러스터를 안정적으로 제어하기 위함 |
| **Data / Tenant Network** | VM 간 통신, Geneve/VXLAN 오버레이 터널링 트래픽 | 사용자 애플리케이션 트래픽으로 대역폭 요구가 높고 가변적 | VM 통신 폭주가 스토리지 I/O나 제어망에 영향을 주는 것을 격리하기 위함 |
| **Storage Network** | Compute-Storage 데이터 읽기/쓰기, 스토리지 노드 간 동기화 | 지속적으로 높은 I/O 성능과 대역폭 요구, 지연 시간에 민감 | 대용량 Disk I/O 트래픽으로 인한 서비스 네트워크 병목을 방지하기 위함 |
| **External / Provider Network** | 외부 인터넷 및 사내망 연결 | 외부 보안 위협에 노출되는 Un-trusted 트래픽 | 외부 공격이나 해킹 시도가 내부망으로 전이되는 것을 방지하기 위함 |

### 3.3 노드 레이어별 권장 하드웨어 스펙

| **노드 유형** | **최소 노드 수** | **CPU (Cores)** | **메모리 (RAM)** | **시스템 디스크** |
| --- | --- | --- | --- | --- |
| **Controller** | 3대 (HA) | 32 Cores 이상 | 128 GB 이상 | NVMe SSD 480GB+ (RAID 1) |
| **Gateway** | 2대 (HA) | 16 Cores 이상 | 64 GB 이상 | Enterprise SSD 240GB+ |
| **Compute** | N대 (가변) | 64 Cores 이상 | 256 GB 이상 | Enterprise SSD 480GB+ |
| **Storage** | 3대 이상 | 32 Cores 이상 | 128 GB 이상 | OS: SSD / Data: NVMe+HDD |

## 4. 가상 머신(VM) 프로비저닝 워크플로우

가상 머신 요청 시 비동기 오케스트레이션이 구동되는 절차는 다음과 같습니다.

```
[Client] ──1. Request──> [nova-api] ──2. Auth Check──> [Keystone]
                             │
                        3. Pass Task
                             ▼
                     [nova-conductor] ──4. Schedule Request──> [nova-scheduler]
                             │                                       │
                             │                                 5. Query Inventory
                             │                                       ▼
                             │                                 [Placement API]
                             ▼
                     [nova-compute] <──6. Target Selected ───────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
   7. Bind Port         8. Attach Vol        9. Launch VM
    [Neutron]          [Glance/Cinder]       [Hypervisor]
```

## 5. Ceph 기반 AWS S3 (RADOS Gateway) 연동

오픈스택 인프라 내부 및 외부 애플리케이션에서 표준 AWS S3 API를 그대로 활용할 수 있도록 Ceph RADOS Gateway(RGW)를 통합 구성합니다.

```
 [ Application / AWS CLI / Boto3 ]
                │
                ▼ (AWS S3 API: HTTP/HTTPS)
    [ HAProxy (Gateway Node) ]
                │
        ┌───────┴───────┐
        ▼               ▼
  [ Ceph RGW 1 ]  [ Ceph RGW 2 ] ───(Ec2-Credentials 인증)───> [ Keystone ]
        │               │
        └───────┬───────┘
                ▼ (RADOS Protocol)
    [ Ceph Storage Cluster ]
```

### 5.1 주요 연동 특징

1. **AWS S3 API 호환성:** AWS SDK(boto3, aws-cli 등) 및 S3 호환 서드파티 도구와 수정 없이 완벽 연동됩니다.
2. **Keystone 멀티테넌트 인증 연동:** RGW는 오픈스택 Keystone과 연동하여 `S3 Access Key / Secret Key`를 발급·인증합니다. 프로젝트(Tenant)별 버킷 생성 권한 및 용량 쿼터(Quota)를 격리 관리합니다.
3. **오픈스택 컴포넌트 백엔드 활용:**
    - **Glance (Image):** OS 이미지를 S3 버킷에 오브젝트 형태로 저장하여 인프라 전반의 이미지 배포 고속화.
    - **Cinder Backup:** 블록 스토리지 볼륨 스냅샷 및 백업 데이터를 S3 오브젝트 스토리지로 보관.
    - **사용자 앱 데이터 백업:** VM 내 애플리케이션 로그, 대용량 파일, 정적 웹 리소스 등의 저장소로 제공.

## 6. 고가용성(HA) 및 확장성(Scale-out) 설계

```
                               [ External Requests / S3 API ]
                                             │
                                             ▼
                                 [ Keepalived (Virtual IP) ]
                                             │
                                   [ HAProxy Load Balancer ]
                                             │
              ┌──────────────────────────────┼──────────────────────────────┐
              ▼                              ▼                              ▼
     [ Controller Node 1 ]          [ Controller Node 2 ]          [ Controller Node 3 ]
      ├─ Stateless APIs              ├─ Stateless APIs              ├─ Stateless APIs
      ├─ MariaDB Galera              ├─ MariaDB Galera              ├─ MariaDB Galera
      ├─ RabbitMQ Quorum             ├─ RabbitMQ Quorum             ├─ RabbitMQ Quorum
      └─ Ceph RGW (S3 Endpoint)      └─ Ceph RGW (S3 Endpoint)      └─ Ceph RGW (S3 Endpoint)
```

### 6.1 제어 영역 고가용성 (Control Plane HA)

- **Stateless API 이중화:** `nova-api`, `keystone-api`, `neutron-server`, **`Ceph RGW (radosgw)`** 등을 컨트롤러/게이트웨이 노드에 Active-Active 상태로 배치하고 상단에 HAProxy 및 Keepalived(VIP)를 연동해 부하 분산 및 장애 우회 연동.
- **Database & Messaging HA:**
    - **MariaDB:** Galera Cluster 기반 동기식 복제 구성으로 노드 파손 시 데이터 유실 방지.
    - **RabbitMQ:** Quorum Queue 기반 분산 큐를 적용하여 메시지 유실 및 중단 방지.

## 7. 기대 효과 및 결론

- **효과적인 장애 격리 및 고가용성 확보:** Control/Data Plane 분리, 4개 독립 네트워크 Plane, Galera/Quorum 3노드 HA 구성을 통해 단일 장애점(SPOF)을 제거하고 비즈니스 연속성을 강화할 수 있습니다.
- **AWS S3 호환성을 통한 하이브리드 확장성 확보:** Ceph RADOS Gateway 통합을 통해 온프레미스 내 S3 환경을 구현함으로써, 향후 AWS 퍼블릭 클라우드 연동 유연성을 확보할 수 있습니다.
- **독립적 Scale-out 기반 운영 효율성 극대화:** 완전 분리형 구조를 통해 제어, 컴퓨트, 스토리지 자원을 필요한 만큼 독립적으로 확장하여 인프라 운영 효율성과 비용 효율성을 높일 수 있습니다.