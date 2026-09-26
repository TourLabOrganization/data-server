# 배포

`develop` 에 푸시되면 GitHub Actions 가 이미지를 빌드해 GHCR 에 올리고, EC2 에서
교체한다. `backend` 레포와 같은 방식이다 (`backend/.github/workflows/cd.yml`).

## 구성

```
[API 인스턴스]   Spring Boot + nginx + certbot   ← 외부 공개 (HTTPS)
                        │
                        │  http://<data-server 사설 IP>:8000
                        ▼
[Data 인스턴스]  FastAPI (이 레포)                ← 외부 비공개
                                                    
[DB 인스턴스]    PostgreSQL                       ← 외부 비공개
```

**data-server 는 외부에 열지 않는다.** 백엔드만 호출하므로 도메인·인증서·nginx 가
전부 필요 없다. 보안그룹에서 8000 포트를 **API 서버의 보안그룹에만** 연다.

## 이미지에 무엇이 들어가는가

파이프라인 산출물(JSON)을 이미지에 **함께 굽는다**. DB도 볼륨도 붙이지 않는다.

- 배포가 곧 데이터 교체가 된다
- 데이터랩은 월 단위 갱신이라 이 주기로 충분하다
- 컨테이너가 상태를 갖지 않아 재기동이 안전하다

그래서 **산출물을 커밋하지 않으면 빈 서버가 뜬다.** CD 가 그걸 먼저 막는다
(`산출물이 커밋돼 있는지 확인` 단계).

---

## 1. EC2 인스턴스 만들기

### 아키텍처를 먼저 정한다

`backend/docs/infra.md` 에는 `t4g.small(arm64)` 로 적혀 있다. **기존 두 인스턴스와
같은 계열로 맞춘다.** 이미지 빌드 플랫폼이 달라지면 컨테이너가 안 뜬다.

| 인스턴스 타입 | 아키텍처 | GitHub Variable `TARGET_PLATFORM` |
|---|---|---|
| `t4g.small` (Graviton) | arm64 | `linux/arm64` (기본값) |
| `t3.small` | amd64 | `linux/amd64` |

### 콘솔에서 만들기

EC2 → 인스턴스 시작

| 항목 | 값 |
|---|---|
| 이름 | `tourlab-data` |
| AMI | Amazon Linux 2023 (아키텍처를 위 표와 맞출 것) |
| 인스턴스 유형 | `t4g.small` 또는 `t3.small` |
| 키 페어 | **기존 두 인스턴스와 같은 것** (CD 가 이 키로 접속한다) |
| VPC · 서브넷 | **API·DB 와 같은 VPC** (사설 IP 로 통신해야 한다) |
| 퍼블릭 IP 자동 할당 | 활성화 (GitHub Actions 가 SSH 로 접속해야 한다) |
| 스토리지 | 20GB gp3 |

### 보안그룹

새로 만든다 — 이름 `tourlab-data-sg`.

| 유형 | 포트 | 소스 | 이유 |
|---|---|---|---|
| 사용자 지정 TCP | 8000 | **API 서버의 보안그룹 ID** | 백엔드만 호출 |
| SSH | 22 | 본인 IP 또는 `0.0.0.0/0` | 배포·점검 |

**8000 을 `0.0.0.0/0` 으로 열지 않는다.** 인증이 없는 API라 그대로 노출된다.

> SSH 를 `0.0.0.0/0` 으로 두는 이유는 GitHub Actions 러너의 IP 가 매번 바뀌기 때문이다.
> 키 인증만 허용되므로 감수할 만하지만, 가능하면 본인 IP 로 좁히고 배포 때만 연다.

---

## 2. 인스턴스 초기 구성 (한 번만)

```bash
ssh -i <키> ec2-user@<퍼블릭 IP>
```

```bash
sudo dnf update -y
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

# docker compose 플러그인 (CD 가 이걸 쓴다)
sudo mkdir -p /usr/local/lib/docker/cli-plugins
ARCH=$(uname -m)   # aarch64 또는 x86_64
sudo curl -sSL \
  "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

exit    # 그룹 권한은 재로그인해야 적용된다
```

재접속 후 확인:

```bash
docker compose version
mkdir -p ~/data-server
```

---

## 3. GitHub 설정

레포 → Settings → Secrets and variables → Actions

**Secrets**

| 이름 | 값 |
|---|---|
| `EC2_HOST` | 새 인스턴스 **퍼블릭 IP** |
| `EC2_USER` | `ec2-user` |
| `EC2_SSH_KEY` | 키 페어의 **.pem 파일 내용 전체** (`-----BEGIN` 줄 포함) |

**Variables** — arm64 면 생략 가능 (기본값)

| 이름 | 값 |
|---|---|
| `TARGET_PLATFORM` | `linux/amd64` (t3 계열일 때만) |

---

## 4. 백엔드에서 호출하기

백엔드 `app.env` 에 추가:

```
DATA_SERVER_URL=http://<data-server 사설 IP>:8000
```

**사설 IP 를 쓴다.** 퍼블릭 IP 로 부르면 트래픽이 인터넷을 돌아 나갔다 들어오고,
보안그룹 규칙(API SG 에서만 허용)에도 걸린다.

연결 확인:

```bash
# API 서버에서
curl -s http://<data-server 사설 IP>:8000/health
```

---

## 5. 첫 배포

`develop` 에 푸시하면 자동으로 돈다. 수동 확인:

```bash
# data-server 인스턴스에서
docker compose -f ~/data-server/docker-compose.yml ps
curl -s http://127.0.0.1:8000/health
docker compose -f ~/data-server/docker-compose.yml logs --tail 50
```

API 문서는 `http://<사설 IP>:8000/docs` 에서 볼 수 있다 (FastAPI 자동 생성).

---

## 데이터만 갱신할 때

코드가 안 바뀌어도 파이프라인 산출물이 바뀌면 재배포해야 한다.

```bash
make all                      # 산출물 재생성
git add data/derived recommend/data/derived
git commit -m "chore: 데이터랩 산출물 갱신"
# develop 에 머지되면 CD 가 새 이미지를 굽는다
```

## 비용

`t4g.small` 기준 월 약 $12 (온디맨드). 공모전 기간만 쓴다면 제출 후 중지하면 된다 —
중지 상태에서는 EBS 요금(20GB 약 $1.6/월)만 나간다.
