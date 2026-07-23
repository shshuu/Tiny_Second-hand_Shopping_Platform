# Tiny Second-hand Shopping Platform

## 핵심 정책과 요구사항 추적

| 요구사항 | 구현 위치 |
|---|---|
| 회원가입·프로필 | `/signup/`, `/profile/`, `/mypage/` |
| 상품 등록·검색·관리 | `/products/new/`, `/`, `/store/` |
| 공용 실시간 채팅 | `/community/`, `/ws/community/` |
| 상품 기반 1:1 채팅 | `/chats/`, `/ws/chat/<room-id>/` |
| 신고·운영 검토 | `/reports/...`, `/operations/reports/` |
| 자동 상품 숨김 | 유효 신고자 3명 임계치 |
| 자동 사용자 임시 제한 | 유효 신고자 5명 임계치 |
| 구매 포인트 정산 | `Purchase`, `WalletTransaction`, `LedgerEntry` |

Tiny Market 포인트는 **과제 시연용 내부 포인트**입니다. 실제 원화·전자화폐가 아니며 충전, 출금, 현금 환급을 제공하지 않습니다. 일반 사용자 간 임의 송금은 제공하지 않으며, ACTIVE 상품의 구매가 완료될 때만 구매자 포인트가 차감되고 판매자에게 같은 금액이 지급됩니다. 가입 축하 포인트와 관리자 지급은 로컬 시연용 지급 기능입니다.

전체 권한, 자동 제재, AuditLog, migration, 공용/1:1 채팅 검증 범위는 [최종 요구사항 추적 문서](docs/final-requirements-traceability.md)를 참조하세요.

신고 누적 사용자는 장기 미접속을 뜻하는 휴면 계정이 아니라 **임시 제한(RESTRICTED)** 상태가 됩니다. 로그인과 공개 상품 조회는 가능하지만 등록·구매·신규 채팅·메시지 전송·신규 신고는 할 수 없습니다.

PostgreSQL 16, Redis 7, Django/Daphne 및 상품 기반 1:1 WebSocket 채팅으로 구성한 중고거래 시연 프로젝트입니다. 일반 사용자의 임의 P2P 포인트 송금은 제공하지 않으며, 포인트는 상품 구매에서만 구매자→판매자로 이전됩니다.

## 빠른 시작: 로컬 데모

사전 요구사항은 Docker Engine 또는 Docker Desktop과 Compose입니다. 아래 기본 명령은 최신 Compose 플러그인(`docker compose`) 기준입니다.

```bash
cp .env.example .env
# .env의 DJANGO_SECRET_KEY= 뒤에 아래 명령으로 만든 값을 붙여 넣습니다.
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
docker compose up -d --build
docker compose ps
docker compose logs -f web
```

`docker compose ps`는 컨테이너 기동 상태만 보여 줍니다. 실제 준비 완료는 `web` 로그에서 migration 오류가 없고 Daphne의 `Listening on TCP address`가 출력된 뒤입니다. `Ctrl+C`는 로그 추적만 중단하며 컨테이너는 계속 실행합니다.

web 컨테이너는 시작 시 committed migration을 자동 적용합니다. fresh DB에서 `up` 직후 별도로 `manage.py migrate`를 동시에 실행하지 마세요. 운영의 여러 web replica에서는 자동 migration 대신 단일 migration job을 사용해야 합니다.

## 기본 카테고리 생성

아래 명령은 **테스트가 아니라 실제 서비스 PostgreSQL DB**에 기본 카테고리 6개를 생성합니다. 실행하지 않으면 상품 등록 화면에 카테고리가 나타나지 않습니다.

```bash
docker compose exec -T web python manage.py seed_categories
```

첫 실행은 `0 existing, 6 created`, 재실행은 `6 existing, 0 created`를 출력합니다. 이 명령은 멱등적이므로 중복 카테고리를 만들지 않습니다.

## Django 검사

```bash
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py makemigrations --check
docker compose exec -T web python manage.py migrate --check
```

기본 주소는 <http://localhost:8000/>입니다. 8000 포트가 사용 중이면 `.env`의 `WEB_PORT=18000`처럼 바꾸고 HTTP와 WebSocket 모두 같은 포트를 사용합니다. Compose project name만 바꾸어도 호스트 포트 충돌은 해결되지 않습니다.

### Legacy standalone Compose

이번 사용자 검증 환경에는 standalone Compose가 설치되어 있어 `docker-compose`를 사용했습니다. Ubuntu 22.04가 반드시 이 문법을 요구하는 것은 아닙니다. 해당 환경에서는 위 명령의 `docker compose`를 `docker-compose`로 바꾸면 됩니다.

`.env`의 `COMPOSE_PROJECT_NAME=tinysecondhand`를 유지하면 두 Compose 문법 모두 같은 프로젝트 이름을 사용합니다. 다른 이름을 쓸 경우 모든 명령에 같은 `-p <name>`을 붙이세요.

## 로컬 데모 환경변수

`.env.example`은 제출·실습용 localhost 데모 기본값입니다.

- `DJANGO_DEBUG=false`, `DJANGO_LOCAL_DEMO_MODE=true`: 안전한 사용자 오류 페이지를 포함한 localhost 전용 시연 모드입니다.
- `SERVE_MEDIA_LOCALLY=true`: 로컬 시연에서만 Django가 재인코딩된 이미지 미디어를 제공합니다.
- `WELCOME_BONUS_ENABLED=true`, `WELCOME_BONUS_AMOUNT=10000`: 로컬 데모용 가입 축하 포인트입니다. 지갑은 먼저 0P로 생성되고, 이어서 append-only `WELCOME_BONUS` 거래와 CREDIT 원장이 생성됩니다.

실제 운영에서는 `DJANGO_LOCAL_DEMO_MODE=false`, `SERVE_MEDIA_LOCALLY=false`로 두고 TLS reverse proxy, 비실행형 media storage/CDN, 방화벽, secret manager를 별도로 구성해야 합니다.

## 사용자 시연 흐름

1. 판매자와 구매자를 각각 `/signup/`에서 만듭니다. 지갑에서 가입 축하 포인트 거래를 확인합니다.
2. 판매자는 상품 등록에서 기본 선택된 **등록 즉시 판매 시작**을 유지하면 ACTIVE 상품이 생성됩니다. 체크를 해제하면 DRAFT로 저장됩니다.
3. 구매자는 ACTIVE 상품 상세에서 **판매자에게 채팅하기**를 누릅니다. 판매자와 구매자 모두 상단 **채팅** 메뉴에서 같은 방을 봅니다.
4. 채팅 페이지는 자동으로 `/ws/chat/<room-id>/`에 연결하고, 공통 메뉴는 `/ws/unread/`에 연결합니다. 사용자가 URL이나 room ID를 직접 입력할 필요는 없습니다. unread 배지는 수신한 읽지 않은 메시지만 최대 `99+`로 표시합니다.
5. 구매자는 ACTIVE 상품 상세 또는 해당 상품의 참여자 채팅방에서만 **구매하기**를 실행합니다. 서버가 DB 상품 가격을 사용해 상품·두 지갑·거래·원장·Purchase·SOLD 상태를 하나의 트랜잭션으로 처리합니다.
6. RESERVED는 상세 조회만 가능하고 구매할 수 없습니다. SOLD는 상세 조회와 기존 참여자 채팅은 유지하지만 신규 채팅·구매는 막습니다. HIDDEN·DELETED·DRAFT는 비소유자에게 공개하지 않습니다.

## 관리자 준비

먼저 일반 회원가입으로 계정을 만든 뒤 로컬 개발 DB에서 역할을 부여합니다.

```bash
docker compose exec -T web python manage.py promote_user your-admin-username --role SUPERADMIN
docker compose exec -T web python manage.py list_admin_users
```

`SUPERADMIN`은 Tiny Market의 `/operations/` 역할입니다. Django의 `is_staff`, `is_superuser`를 자동으로 부여하지 않습니다. `/admin/`은 공식 운영 UI가 아니며, 운영 기능은 `/operations/login/`과 `/operations/`에 있습니다.

운영 화면에서는 대시보드·사용자·상품·신고·**자동 조치**·**공용 채팅**·거래·카테고리·감사 로그를 공통 메뉴로 이동할 수 있습니다. MODERATOR는 신고·자동 조치·메시지 숨김을 검토할 수 있고, ADMIN/SUPERADMIN은 사용자 상태·카테고리·지급 같은 추가 운영 조치를 수행합니다. 자동 조치는 담당자 배정, 사유 없는 검토 시작, 사유가 필요한 승인/기각으로 처리하며 완료 뒤에는 결과 카드만 남습니다.

## 공용 채팅과 자동 제재

- 공용 채팅은 `/community/`(WebSocket: `/ws/community/`)의 로그인 사용자 공용 공간입니다. ACTIVE 계정만 전송할 수 있고 RESTRICTED 계정은 조회만 가능합니다. SUSPENDED·비활성 계정은 접근할 수 없습니다. 메시지는 Redis 제한을 적용하며 Redis 장애에서는 전송을 fail-closed로 거부합니다.
- 공용 채팅 메시지는 신고할 수 있습니다. 운영자는 공용 채팅 메뉴에서 신고 수·발신자·내용·작성 시각을 확인하고 사유를 적어 숨길 수 있습니다. 숨긴 원문은 일반 사용자에게 다시 노출하지 않습니다.
- 서로 다른 ACTIVE 신고자 3명이 ACTIVE/RESERVED 상품을 신고하면 임시 HIDDEN, 5명이 ACTIVE 사용자를 신고하면 임시 RESTRICTED가 됩니다. 중복·자기 신고와 제한/비활성 신고자는 집계하지 않습니다. 기각은 자동 조치 상태가 그대로일 때만 기록된 이전 상태로 복구하므로, 이후의 수동 상태 변경을 덮어쓰지 않습니다.

## 권한과 미디어 확인

컨테이너가 root가 아닌 `appuser`로 실행되는지, writable volume이 준비됐는지는 다음처럼 확인할 수 있습니다.

```bash
docker compose exec -T --user 1000:1000 web sh -c 'id; test -w /app/media; test -w /app/staticfiles'
```

`media_data` named volume은 web 재시작 후에도 유지됩니다. 모든 업로드는 JPEG/PNG/WebP 검증·재인코딩 및 UUID 파일명 정책을 따릅니다.

## 테스트와 종료

```bash
docker compose exec -T web python manage.py test tests --noinput
docker compose down
# PostgreSQL 및 media named volume까지 삭제하는 로컬 초기화:
docker compose down -v
```

Redis fail-closed 테스트는 의도적으로 backend 오류 로그를 남길 수 있습니다. 이 경우 민감 기능은 거부되며 HTTP 응답에는 traceback이 노출되지 않아야 합니다.

## 검증 범위

Codex의 자동 검증은 Windows/Docker Desktop의 PostgreSQL·Redis Docker 환경에서 수행됩니다. VMware Workstation Ubuntu 22.04 Desktop fresh-clone 브라우저 수용시험은 사용자가 별도로 수행하며, 두 환경의 결과를 혼동하지 않습니다. 자세한 절차는 [독립 검증 안내서](docs/independent-verification-guide.md)와 [fresh-clone 후속 검증 기록](docs/followup-fresh-clone-usability-verification.md)을 참고하세요.
