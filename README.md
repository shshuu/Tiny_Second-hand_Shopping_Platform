# Tiny Second-hand Shopping Platform

PostgreSQL 16, Redis 7, Django, Channels로 구성한 중고거래 플랫폼입니다. 독립 검증 후속 보완을 포함한 PostgreSQL·Redis 통합 회귀 테스트 77/77을 완료했으며, 현재 기능 동결 상태입니다.

## 주요 기능

- 원자적 회원가입: 사용자·프로필·0P 지갑·선택적 환영 포인트 거래/원장 생성
- 상품 등록·검색·상태 전이·안전한 이미지 재인코딩 업로드
- 전체/1:1 채팅, Redis Channel Layer 기반 WebSocket, 차단·제한 상태 적용
- 사용자·상품·메시지 신고, 자동 HIDDEN/RESTRICTED 조치와 감사 이력
- 멱등성·한도·원장·REVERSAL 기반 포인트 송금 및 관리자 지급
- 역할 기반 운영 화면, 재인증, 세션 정책, 불변 감사 로그
- Host·CSRF·HTTPS/HSTS·CSP·쿠키·운영 미디어 분리 보안 설정
- Redis fail-closed 회원가입 및 일반 로그인 실패 속도 제한

## 기술 스택

- Python / Django / Django Channels / Daphne
- PostgreSQL 16
- Redis 7 / channels-redis
- Pillow, WhiteNoise
- Docker Compose

## 디렉터리 구조

```text
.
├── config/                 # Django settings, ASGI/WSGI, URL 설정
├── market/                 # 앱 모델·서비스·뷰·Consumer·템플릿
├── market/migrations/      # PostgreSQL 스키마·트리거 마이그레이션
├── tests/                  # PostgreSQL·Redis 통합 테스트
├── docs/                   # 최종 산출물·독립 검증 안내·운영 문서
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── manage.py
```

## 사전 요구사항

- Docker Desktop 또는 Docker Engine
- Docker Compose v2 (`docker compose` 명령)

## 환경변수 준비

개발용 예시를 복사합니다.

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env.example`의 DB/Redis 자격증명은 로컬 Compose 개발 전용 예시입니다. 운영에서는 별도 비밀값, 운영 Host, HTTPS CSRF Origin, 프록시 정책을 사용해야 합니다.

## 최초 실행

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f web
```

웹 주소: <http://localhost:8000/>

8000 포트를 다른 프로그램이 사용 중이면 `.env`의 `WEB_PORT=18000`처럼 변경한 뒤 `http://localhost:18000/`으로 접속합니다. Compose project name 변경만으로는 호스트 포트 충돌이 해결되지 않습니다.

The web container applies committed migrations automatically at startup. `docker compose ps` confirms container startup only; it does not prove that migrations are complete. Follow `docker compose logs -f web` and wait for committed migrations to finish without an error and for Daphne to print `Listening on TCP address`. Press `Ctrl+C` only to stop log follow; the containers keep running. On a fresh database, do not run a separate `manage.py migrate` concurrently with `docker compose up`. In production, use one dedicated migration job rather than allowing multiple web replicas to migrate concurrently.

## 마이그레이션 및 검사

```bash
docker compose exec -T web python manage.py check
docker compose exec -T web python manage.py makemigrations --check
docker compose exec -T web python manage.py migrate --check
```

`migrate --check` only reports whether unapplied migrations exist; it does not apply migrations.

## 전체 테스트

실제 PostgreSQL·Redis 환경의 전체 테스트 명령입니다.

```bash
docker compose exec -T web python manage.py test tests --noinput
```

기대 결과는 `Ran 77 tests ... OK`입니다. Redis fail-closed 테스트 중 의도적으로 Redis backend 오류 로그가 출력될 수 있습니다. 이는 장애 시 요청을 안전하게 거부하는지 확인하는 테스트이며, 실제 HTTP 응답에는 예외나 스택 트레이스가 노출되지 않습니다.

## 관리자 계정 준비

관리자 계정이나 비밀번호는 저장소에 포함하지 않습니다. 먼저 일반 회원가입으로 계정을 만든 뒤, 로컬 개발 DB에서 Django shell을 통해 역할을 명시적으로 부여합니다.

```bash
docker compose exec -T web python manage.py shell
```

```python
from market.models import User
user = User.objects.get(username="your-admin-username")
user.role = User.Role.SUPERADMIN  # 필요한 최소 역할을 선택
user.save(update_fields=["role"])
```

운영 환경에서는 초기 관리자 생성·역할 부여를 승인된 운영 절차와 감사 로그 정책으로 처리해야 합니다. 관리자 로그인은 `/operations/login/`, 운영 화면은 `/operations/`입니다.

## WebSocket 채팅 확인

1. 두 사용자로 로그인하고 전체 채팅 또는 1:1 채팅방을 준비합니다.
2. 브라우저 개발자 도구 또는 WebSocket 클라이언트에서 다음 경로로 세션 쿠키를 포함해 연결합니다.

   ```text
   ws://localhost:8000/ws/chat/<chat-room-public-id>/
   ```

   This is the default `WEB_PORT=8000` example. HTTP and WebSocket use the same host port: with `.env` `WEB_PORT=18000`, use `http://localhost:18000/` and `ws://localhost:18000/ws/chat/<chat-room-public-id>/`.

3. `{"content":"hello"}` 형식으로 전송하면 같은 방의 다른 연결에 전달되고 DB에 저장됩니다.

운영 HTTPS 환경에서는 반드시 `wss://`와 동일 출처 연결을 사용합니다.

## 종료 및 데이터 초기화

컨테이너 종료:

```bash
docker compose down
```

PostgreSQL 볼륨까지 삭제하는 로컬 개발 초기화(복구 불가):

```bash
docker compose down -v
```

로컬 업로드 미디어도 초기화하려면 `media/`를 별도로 삭제해야 합니다. 이 디렉터리는 Git과 제출 ZIP에 포함되지 않습니다.

## 문서

- [§28 최종 산출물](docs/tiny-secondhand-platform-section28-final.md)
- [최종 구현 기준 설계 변경사항](docs/as-built-design-deviations.md)
- [독립 검증 안내서](docs/independent-verification-guide.md)
- [§28-10 보안 강화 문서](docs/28_security_hardening.md)
- [인증 rate-limit 후속 검증](docs/followup-auth-rate-limit-verification.md)
- [운영 모니터링 runbook](docs/operations_monitoring.md)

## 운영 배포 전 별도 확인

- TLS 프록시만 외부 노출하고 웹·PostgreSQL·Redis 직접 포트를 비공개로 유지
- 외부 `X-Forwarded-Proto` 제거 후 프록시가 자체 HTTPS 값을 설정
- 실제 인증서·갱신·방화벽·보안 그룹·네트워크 ACL 검증
- 시크릿 매니저 기반 자격증명 주입과 DB 백업·복구 훈련
- SIEM/경보 연동, 관리자 MFA, 계정·IP 단독 로그인 제한 및 rate-limit 고도화
- 의존성·컨테이너 이미지 정기 취약점 스캔
