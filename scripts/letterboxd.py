"""Etapa 2: nota, nº de avaliações e diretor no Letterboxd (JSON-LD), com retomada."""
import argparse, csv, json, os, random, re, subprocess, time
import urllib.error, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CATALOGO, SAIDA, SEM_NOTA = "data/catalogo.csv", "data/letterboxd.csv", "data/sem_nota.csv"
CAMPOS_LB = ["imdb_id", "nota_letterboxd", "avaliacoes_letterboxd", "diretor", "url_letterboxd"]
CAMPOS_SN = ["jw_id", "imdb_id", "titulo_original", "titulo_pt", "ano", "servicos", "motivo"]
SALVAR_A_CADA, COMMIT_A_CADA = 50, 500
LDJSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def ler(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def anexar(caminho, campos, linhas):
    novo = not os.path.exists(caminho)
    with open(caminho, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, campos, extrasaction="ignore")
        if novo:
            w.writeheader()
        w.writerows(linhas)


def git_commit(msg):
    subprocess.run(["git", "add", SAIDA, SEM_NOTA], check=False)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", msg + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
                    "Claude-Session: https://claude.ai/code/session_01XeQftFaY5on4kgbm3okFRL"], check=False)
    ramo = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    for espera in (2, 4, 8, 16, 0):
        if subprocess.run(["git", "push", "-q", "-u", "origin", ramo]).returncode == 0:
            return
        time.sleep(espera)
    print("  aviso: push falhou; fica para o próximo commit", flush=True)


def baixar(imdb_id):
    """Devolve (url_final, html) ou (None, motivo)."""
    url = f"https://letterboxd.com/imdb/{imdb_id}/"
    for espera in (60, 120, 300, 300, 300, None):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.geturl(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, "nao_encontrado_letterboxd"
            if e.code not in (403, 429) and e.code < 500:
                return None, f"erro_http_{e.code}"
            erro = f"HTTP {e.code}"
        except Exception as e:  # rede
            erro = repr(e)
        if espera is None:
            return None, "erro_consulta"
        print(f"  {imdb_id}: {erro}; esperando {espera}s", flush=True)
        time.sleep(espera)


def extrair(html):
    for bloco in LDJSON.findall(html):
        bloco = re.sub(r"/\*.*?\*/", "", bloco, flags=re.S).strip()
        try:
            d = json.loads(bloco)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Movie":
            ag = d.get("aggregateRating") or {}
            dirs = d.get("director") or []
            if isinstance(dirs, dict):
                dirs = [dirs]
            return ag.get("ratingValue"), ag.get("ratingCount"), ", ".join(x.get("name", "") for x in dirs)
    return None, None, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, help="processa no máximo N filmes (teste)")
    ap.add_argument("--sem-commit", action="store_true")
    a = ap.parse_args()

    catalogo = ler(CATALOGO)
    feitos = {r["imdb_id"] for r in ler(SAIDA)} | {r["imdb_id"] or "jw" + r["jw_id"] for r in ler(SEM_NOTA)}

    # filmes sem IMDb ID vão direto para sem_nota
    sem_id = [{**f, "motivo": "sem_imdb_id"} for f in catalogo
              if not f["imdb_id"] and "jw" + f["jw_id"] not in feitos]
    if sem_id:
        anexar(SEM_NOTA, CAMPOS_SN, sem_id)

    fila, vistos = [], set()
    for f in catalogo:
        if f["imdb_id"] and f["imdb_id"] not in feitos and f["imdb_id"] not in vistos:
            vistos.add(f["imdb_id"])
            fila.append(f)
    if a.limite:
        fila = fila[:a.limite]
    print(f"Já processados: {len(feitos)} | na fila: {len(fila)}", flush=True)

    buf_lb, buf_sn, desde_commit, inicio = [], [], 0, time.time()
    for i, f in enumerate(fila, 1):
        url, html = baixar(f["imdb_id"])
        if url is None:
            buf_sn.append({**f, "motivo": html})
        elif "/film/" not in url:
            buf_sn.append({**f, "motivo": "nao_encontrado_letterboxd"})
        else:
            nota, n, diretor = extrair(html)
            if nota is None:
                buf_sn.append({**f, "motivo": "sem_nota_letterboxd"})
            else:
                buf_lb.append({"imdb_id": f["imdb_id"], "nota_letterboxd": nota,
                               "avaliacoes_letterboxd": n or 0, "diretor": diretor,
                               "url_letterboxd": url})
        desde_commit += 1
        if i % SALVAR_A_CADA == 0 or i == len(fila):
            anexar(SAIDA, CAMPOS_LB, buf_lb)
            anexar(SEM_NOTA, CAMPOS_SN, buf_sn)
            buf_lb, buf_sn = [], []
            ritmo = (time.time() - inicio) / i
            print(f"[{time.strftime('%H:%M:%S')}] {i}/{len(fila)} | ~{ritmo * (len(fila) - i) / 3600:.1f} h restantes", flush=True)
            if not a.sem_commit and (desde_commit >= COMMIT_A_CADA or i == len(fila)):
                git_commit(f"Letterboxd: +{desde_commit} filmes ({i}/{len(fila)} desta rodada)")
                desde_commit = 0
        time.sleep(random.uniform(3, 5))


if __name__ == "__main__":
    main()
