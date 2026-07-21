# Tiny Second-hand Shopping Platform

Docker Compose로 실행하는 중고거래 시연 프로젝트입니다. Django/Daphne, PostgreSQL 16, Redis 7과 상품 기반 1:1 WebSocket 채팅을 사용합니다.

## 주요 기능

- 회원가입 시 프로필·0P 지갑을 원자적으로 생성하고, 로컬 데모에서는 `WELCOME_BONUS` 거래와 원장으로 가입 포인트를 지급합니다.
- 상품 등록, 안전한 JPEG/PNG/WebP 재인코딩 업로드(최대 5장), 검색, 상태 전이, 내 스토어를 제공합니다.
- 구매자가 상품 상세에서 채팅을 시작하면 판매자와 구매자의 채팅 목록에 같은 1:1 방이 나타납니다. 사용자가 WebSocket URL이나 방 ID를 직접 입력할 필요는 없습니다.
- 지갑 송금, 신고·제한, `/operations/` 운영 화면, PostgreSQL 거래·원장 불변성 제약을 제공합니다.

## 사전 요구사항

- Docker Desktop 또는 Docker Engine
- Docker Compose v2 (`docker compose`)

## 깨끗한 환경에서 처음 실행하기

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose logs -f web
```

Windows PowerShell에서는 첫 줄을 다음으로 바꿉니다.

```powershell
Copy-Item .env.example .env
```

`docker compose ps`는 컨테이너가 시작되었는지만 보입니다. 실제 준비 완료는 `web` 로그에서 **migration 오류 없이 적용이 끝난 것**과 Daphne의 `Listening on TCP address` 메시지를 확인해야 합니다. `Ctrl+C`는 로그 보기만 끝내며 컨테이너는 계속 실행됩니다.

web 컨테이너는 시작 시 committed migration을 자동 적용합니다. fresh DB에서 `up` 직후 별도의 `manage.py migrate`를 동시에 실행하지 마세요. 운영의 여러 web replica에서는 자동 migration 대신 하나의 전용 migration job을 사용해야 합니다.

로그 확인 뒤 기본 카테고리를 준비합니다. 두 번 실행해도 중복되지 않습니다.

```bash
docker compose exec -T web python manage.py seed_categories
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py makemigrations --check
docker compose exec -T web python manage.py migrate --check
```

기본 접속 주소는 <http://localhost:8000/>입니다. 8000 포트가 사용 중이면 `.env`에서 `WEB_PORT=18000`처럼 바꾸고, <http://localhost:18000/>으로 접속합니다. Compose project name을 바꾸는 것만으로 호스트 포트 충돌은 해결되지 않습니다.

## 로컬 데모 데이터와 사용자 흐름

`.env.example`은 로컬 시연 편의를 위해 다음 값을 사용합니다.

```env
WELCOME_BONUS_ENABLED=true
WELCOME_BONUS_AMOUNT=10000
```

지갑은 언제나 먼저 **0P**로 만들어집니다. 위 설정이 true이면 같은 가입 트랜잭션에서 `WELCOME_BONUS` 거래와 CREDIT 원장이 하나 생성되어 최종 잔액이 10,000P가 됩니다. 운영에서 가입 프로모션을 제공하지 않으면 `WELCOME_BONUS_ENABLED=false`로 설정합니다.

1. 판매자 계정을 `/signup/`에서 만들고 지갑에서 가입 포인트를 확인합니다.
2. 판매자로 로그인해 **상품 등록**을 선택하고 카테고리·한국어 상품명·설명·이미지를 입력합니다. 카테고리가 없다면 위 `seed_categories` 명령을 실행합니다.
3. 상품 상태를 `판매 시작(ACTIVE)`으로 바꿉니다.
4. 다른 브라우저 또는 시크릿 창에서 구매자 계정을 만듭니다.
5. 구매자가 상품 상세에서 **판매자에게 채팅하기**를 누르고 메시지를 보냅니다.
6. 판매자와 구매자 모두 상단 **채팅** 메뉴에서 같은 방을 열어 답장합니다. 새로고침해도 저장된 메시지가 보입니다.
7. 구매자는 **지갑**에서 판매자 username으로 송금합니다. 존재하지 않는 username은 화면 내 입력 오류로 처리되며 거래가 생성되지 않습니다.

신규 채팅은 ACTIVE 상품에서만 만들 수 있습니다. SOLD/HIDDEN/DELETED/DRAFT 상품에서는 새 방을 만들 수 없고, 기존 상품 채팅은 거래 후속 협의를 위해 채팅 목록에서 보존됩니다. RESERVED 상품도 신규 방 생성은 허용하지 않습니다.

### 채팅 개발자 확인

일반 사용자는 raw WebSocket URL을 입력하지 않습니다. 상세 페이지 JavaScript가 자동 연결합니다. 개발자 진단 시 기본 설정은 `ws://localhost:8000/ws/chat/<room-public-id>/`이며, `WEB_PORT=18000`이면 `ws://localhost:18000/ws/chat/<room-public-id>/`입니다. HTTP와 WebSocket은 같은 호스트 포트를 사용합니다.

## 관리자 준비와 URL 정책

먼저 일반 회원가입으로 계정을 만든 후, 로컬 개발 DB에서 역할을 부여합니다.

```bash
docker compose exec -T web python manage.py promote_user your-admin-username --role SUPERADMIN
docker compose exec -T web python manage.py list_admin_users
```

명령은 존재하지 않는 username 또는 허용되지 않은 role을 오류로 처리하고, 변경 전후 role만 출력합니다. 비밀번호는 출력하지 않습니다. 운영 화면은 <http://localhost:8000/operations/login/>이며 역할 기반 운영 UI는 `/operations/`입니다.

`/admin/`은 프로젝트의 공식 운영 UI가 아니며 외부 URL로 노출하지 않습니다. Django의 `is_staff`/`is_superuser`는 `/admin/` 접근용 Django 기본 속성이고, 프로젝트 운영 권한은 `USER`, `MODERATOR`, `ADMIN`, `SUPERADMIN`의 `role` 필드로 판정합니다.

## 미디어 저장소와 권한

상품 이미지는 호스트 bind mount가 아닌 Compose named volume `media_data`에 저장합니다. 시작 스크립트가 `/app/media`와 `/app/staticfiles` 소유권을 `appuser`에게 초기화한 뒤 Django를 비루트 사용자로 실행합니다. 따라서 Ubuntu Docker Engine과 Docker Desktop 모두 fresh clone 후 수동 `chmod 777` 또는 `chown` 없이 업로드할 수 있습니다. `docker compose down` 후에도 이미지는 유지되고, `docker compose down -v`는 PostgreSQL 및 미디어 named volume까지 삭제합니다.

## 시연용 DEBUG=False

기능 개발은 `.env.example`의 `DJANGO_DEBUG=true`로 시작합니다. localhost에서 사용자 오류 페이지를 시연하려면 `.env`에서 `DJANGO_DEBUG=false`, `DJANGO_LOCAL_DEMO_MODE=true`로 바꾼 뒤 재기동합니다. 이 모드는 localhost 전용으로 강제되며 HTTPS redirect와 Secure 쿠키를 끄므로 **인터넷에 공개하면 안 됩니다**. 실제 운영 `DEBUG=false`는 HTTPS TLS proxy, 안전한 secret, 비개발 DB/Redis 자격증명, 허용 Host와 HTTPS CSRF origin이 필요합니다. [보안 문서](docs/28_security_hardening.md)의 운영 체크리스트를 따르세요.

없는 URL은 `DEBUG=false`에서 사용자용 400/403/404/500 템플릿으로 처리되며 내부 URLconf·view 이름·스택 정보를 표시하지 않습니다.

## 테스트

실제 PostgreSQL·Redis 컨테이너에서 실행합니다.

```bash
docker compose exec -T web python manage.py test tests --noinput
```

이전 기준은 77개 테스트였습니다. 현재 수정에서는 P0/P1 사용자 흐름 테스트가 추가되므로, 결과 수는 실행 출력으로 확인하고 검증 보고에 기록합니다. Redis fail-closed 테스트는 의도적으로 backend 오류 로그를 남길 수 있으나, 해당 HTTP 응답에는 스택 트레이스가 노출되지 않아야 합니다.

## 종료와 데이터 초기화

```bash
docker compose down
docker compose down -v  # PostgreSQL 및 media_data까지 삭제하는 로컬 초기화
```

## 문제 해결

- 상품 등록에 카테고리가 없으면 `seed_categories`를 실행합니다.
- `web` 로그에 migration 오류가 있으면 `docker compose down -v`로 로컬 데이터만 초기화한 뒤 처음 실행 순서를 다시 수행합니다.
- 이미지 업로드 실패 시 `docker compose ps`로 web이 최신 이미지인지 확인합니다. named volume 방식에서는 호스트 media 권한을 수동 변경하지 않습니다.
- 채팅이 보이지 않으면 두 계정이 상품의 판매자·구매자인지, 상품이 ACTIVE일 때 방을 만들었는지, 상단 **채팅** 메뉴를 열었는지 확인합니다.

## 문서

- [§28 최종 산출물](docs/tiny-secondhand-platform-section28-final.md)
- [최종 구현 기준 설계 차이](docs/as-built-design-deviations.md)
- [독립 검증 안내서](docs/independent-verification-guide.md)
- [§28-10 보안 문서](docs/28_security_hardening.md)
- [운영 모니터링 runbook](docs/operations_monitoring.md)
- [fresh-clone 사용성 후속 검증](docs/followup-fresh-clone-usability-verification.md)
