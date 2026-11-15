"""Auditoria do catálogo contra o JustWatch e outras fontes.

Uso (na raiz do repositório):
  python3 scripts/auditoria.py chegadas <lista.json>   # novidades do mês (Parte 2)
  python3 scripts/auditoria.py mubi <films.json.gz>    # cruza com o dataset kubi (BR)
  python3 scripts/auditoria.py saidas <catalogo_anterior.csv>  # saídas falsas
  python3 scripts/auditoria.py amostra [n]             # amostra de controle (padrão 25)

lista.json: [{"servico", "titulo", "ano", "data", "fonte", "url", "oficial"}]
Toda correção vai para data/correcoes_manuais.csv; quem foi adicionado ou devolvido
ganha as datas de saída do JustWatch em data/fontes/justwatch_saidas.json.
O resultado item a item de cada etapa fica em data/fontes/auditoria_<etapa>_<data>.csv.
"""
import csv, gzip, json, random, sys, time, urllib.request
from datetime import date, datetime, timezone

sys.path.insert(0, "scripts")
from jw_catalogo import SERVICOS, ORDEM, DURACAO_MIN, SAIDAS_JW, CATALOGO, datas_saida
from saindo import norm, parecido

HOJE = date.today().isoformat()
CORRECOES = "data/correcoes_manuais.csv"
CAMPOS_COR = ["imdb_id", "servico", "acao", "fonte", "data", "titulo_original", "jw_id"]
PACOTE = {v: k for k, v in SERVICOS.items() if k not in ("nfa", "ppp")}  # serviço -> código

CAMPOS_JW = """objectId objectType
 content(country:BR,language:"pt"){title originalTitle originalReleaseYear runtime
   externalIds{imdbId tmdbId} scoring{imdbScore imdbVotes}}
 en:content(country:US,language:"en"){title}
 offers(country:BR,platform:WEB){monetizationType availableToTime package{shortName}}"""


def gql(query, variables=None):
    corpo = json.dumps({"query": query, "variables": variables or {}}).encode()
    for tentativa in range(5):
        try:
            req = urllib.request.Request("https://apis.justwatch.com/graphql", corpo,
                                         {"content-type": "application/json", "user-agent": "Mozilla/5.0"})
            d = json.load(urllib.request.urlopen(req, timeout=60))
            if d.get("errors") and not d.get("data"):
                raise RuntimeError(d["errors"])
            time.sleep(0.3)
            return d["data"]
        except Exception as e:
            print("  erro JustWatch:", e, flush=True)
            time.sleep(5 * (tentativa + 1))
    raise SystemExit("JustWatch falhou 5 vezes")


def resumo(no):
    """Nó do JustWatch -> dict com dados do filme e serviços FLATRATE no BR."""
    if not no or no.get("objectType") != "MOVIE":
        return None
    c = no["content"]
    ofertas = [o for o in no["offers"] or []
               if o["monetizationType"] == "FLATRATE" and o["package"]["shortName"] in SERVICOS]
    return {"jw_id": str(no["objectId"]), "titulo_pt": c["title"],
            "titulo_original": c["originalTitle"] or c["title"], "ano": c["originalReleaseYear"] or "",
            "duracao_min": c["runtime"] or "", "imdb_id": (c["externalIds"] or {}).get("imdbId") or "",
            "imdb_nota": (c["scoring"] or {}).get("imdbScore") or "",
            "imdb_votos": (c["scoring"] or {}).get("imdbVotes") or "",
            "titulos": {c["title"], c["originalTitle"], (no.get("en") or {}).get("title")} - {None},
            "servicos": {SERVICOS[o["package"]["shortName"]] for o in ofertas},
            "saidas": datas_saida(ofertas)}


def ofertas_jw(jw_ids):
    """{jw_id: resumo} consultando os nós em lotes de 20."""
    out, ids = {}, [i for i in jw_ids if str(i).isdigit()]
    for k in range(0, len(ids), 20):
        lote = ids[k:k + 20]
        q = "query{" + " ".join(f'n{i}:node(id:"tm{j}"){{... on Movie{{{CAMPOS_JW}}}}}'
                                for i, j in enumerate(lote)) + "}"
        d = gql(q)
        for i, j in enumerate(lote):
            out[str(j)] = resumo(d.get(f"n{i}"))
    return out


def buscar_jw(titulo, ano=None):
    """Candidatos da busca do JustWatch BR com título parecido e ano ±1."""
    q = f"""query($q:String!){{popularTitles(country:BR,first:10,
      filter:{{searchQuery:$q,objectTypes:[MOVIE]}}){{edges{{node{{{CAMPOS_JW}}}}}}}}}"""
    nos = gql(q, {"q": titulo})["popularTitles"]["edges"]
    cands = []
    for e in nos:
        r = resumo(e["node"])
        if not r or (ano and r["ano"] and abs(int(r["ano"]) - int(ano)) > 1):
            continue
        if any(parecido(titulo, t) for t in r["titulos"]):
            cands.append(r)
    return cands


class Catalogo:
    def __init__(self):
        with open(CATALOGO, encoding="utf-8") as fh:
            leitor = csv.DictReader(fh)
            self.campos, self.linhas = leitor.fieldnames, list(leitor)
        with open(SAIDAS_JW, encoding="utf-8") as fh:
            self.saidas_jw = json.load(fh)
        try:
            with open(CORRECOES, encoding="utf-8") as fh:
                self.correcoes = list(csv.DictReader(fh))
        except FileNotFoundError:
            self.correcoes = []

    def achar(self, jw_id="", imdb_id=""):
        for f in self.linhas:
            if (jw_id and f["jw_id"] == str(jw_id)) or (imdb_id and f["imdb_id"] == imdb_id):
                return f
        return None

    def tem(self, f, serv):
        return f is not None and serv in f["servicos"].split("|")

    def adicionar(self, serv, info, acao, fonte):
        """Põe o serviço no filme (criando a linha se preciso) e registra a correção."""
        f = self.achar(info.get("jw_id"), info.get("imdb_id"))
        if f is None:
            f = {c: "" for c in self.campos}
            for c in self.campos:
                if c in info and c not in ("servicos", "sai_em"):
                    f[c] = info[c]
            self.linhas.append(f)
        servs = set(filter(None, f["servicos"].split("|"))) | {serv}
        f["servicos"] = "|".join(s for s in ORDEM if s in servs)
        if info.get("saidas") is not None and f["jw_id"].isdigit():
            self.saidas_jw[f["jw_id"]] = {"imdb_id": f["imdb_id"], "saidas": info["saidas"]}
        self.registrar(f, serv, acao, fonte)
        return f

    def remover(self, f, serv, acao, fonte):
        f["servicos"] = "|".join(s for s in f["servicos"].split("|") if s != serv)
        self.registrar(f, serv, acao, fonte)
        if not f["servicos"]:
            self.linhas.remove(f)

    def registrar(self, f, serv, acao, fonte):
        chave = (f["imdb_id"] or f["jw_id"], serv, acao)
        if any((c["imdb_id"] or c["jw_id"], c["servico"], c["acao"]) == chave for c in self.correcoes):
            return
        self.correcoes.append({"imdb_id": f["imdb_id"], "servico": serv, "acao": acao, "fonte": fonte,
                               "data": HOJE, "titulo_original": f["titulo_original"].strip(),
                               "jw_id": f["jw_id"]})

    def salvar(self):
        with open(CATALOGO, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, self.campos)
            w.writeheader()
            w.writerows(sorted(self.linhas, key=lambda f: str(f["titulo_original"]).lower()))
        with open(SAIDAS_JW, "w", encoding="utf-8") as fh:
            json.dump(self.saidas_jw, fh)
        with open(CORRECOES, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, CAMPOS_COR)
            w.writeheader()
            w.writerows(self.correcoes)


def gravar_resultado(etapa, linhas, campos):
    caminho = f"data/fontes/auditoria_{etapa}_{HOJE}.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(linhas)
    return caminho


def contar(linhas, chave="resultado"):
    cont = {}
    for l in linhas:
        cont[(l["servico"], l[chave])] = cont.get((l["servico"], l[chave]), 0) + 1
    for s in ORDEM:
        partes = [f"{r}={n}" for (sv, r), n in sorted(cont.items()) if sv == s]
        if partes:
            print(f"  {s:12} " + ", ".join(partes))


def chegadas(lista):
    cat, res = Catalogo(), []
    for it in json.load(open(lista, encoding="utf-8")):
        serv, linha = it["servico"], dict(it)
        if it.get("data") and it["data"] > HOJE:
            linha["resultado"] = "ainda_nao_estreou"
        else:
            cands = buscar_jw(it["titulo"], it.get("ano"))
            ja = next((c for c in cands if cat.tem(cat.achar(c["jw_id"], c["imdb_id"]), serv)), None)
            com_oferta = next((c for c in cands if serv in c["servicos"]), None)
            alvo = ja or com_oferta or (cands[0] if cands else None)
            if alvo:
                linha.update(jw_id=alvo["jw_id"], imdb_id=alvo["imdb_id"], titulo_jw=alvo["titulo_original"])
            if ja:
                linha["resultado"] = "ja_no_catalogo"
            elif alvo and alvo["duracao_min"] and int(alvo["duracao_min"]) < DURACAO_MIN:
                linha["resultado"] = "curta_ignorado"
            elif com_oferta:
                cat.adicionar(serv, com_oferta, "adicionado_justwatch", it["fonte"])
                linha["resultado"] = "adicionado_justwatch"
            elif alvo and it.get("oficial"):
                cat.adicionar(serv, alvo, "adicionado_fonte_oficial", it["fonte"])
                linha["resultado"] = "adicionado_fonte_oficial"
            elif alvo:
                linha["resultado"] = "justwatch_sem_oferta"
            else:
                linha["resultado"] = "nao_encontrado_justwatch"
        res.append(linha)
        print(f"  {serv:11} {linha['resultado']:24} {it['titulo']} ({it.get('ano')})", flush=True)
    cat.salvar()
    print("Resultado:", gravar_resultado("chegadas", res, ["servico", "titulo", "ano", "data", "fonte", "url",
                                                          "resultado", "jw_id", "imdb_id", "titulo_jw"]))
    contar(res)


def mubi(films_gz):
    cat, res = Catalogo(), []
    agora = datetime.now(timezone.utc).isoformat()
    vivos = {}
    for m in json.load(gzip.open(films_gz))["items"]:
        br = (m.get("available_countries") or {}).get("BR") or {}
        if (br.get("availability") == "live" and (br.get("available_at") or "") <= agora
                and (br.get("availability_ends_at") or "9") > agora):
            vivos[m.get("imdb_id") or f"mubi{m['mubi_id']}"] = m

    # 1) disponível no kubi e fora do catálogo da MUBI
    for imdb, m in vivos.items():
        if (m.get("duration") or 0) < DURACAO_MIN or not m.get("imdb_id"):
            continue
        f = cat.achar(imdb_id=imdb)
        if cat.tem(f, "MUBI"):
            continue
        linha = {"servico": "MUBI", "sentido": "kubi_sem_catalogo", "imdb_id": imdb,
                 "titulo": m.get("original_title") or m["title"], "ano": m.get("year")}
        jw = None
        if f and f["jw_id"].isdigit():
            jw = ofertas_jw([f["jw_id"]]).get(f["jw_id"])
        if not jw:
            cands = buscar_jw(m.get("original_title") or m["title"], m.get("year")) or \
                buscar_jw(m["title"], m.get("year"))
            jw = next((c for c in cands if c["imdb_id"] == imdb), None) or \
                next((c for c in cands if "MUBI" in c["servicos"]), None)
        if jw and jw["duracao_min"] and int(jw["duracao_min"]) < DURACAO_MIN:
            linha["resultado"] = "curta_ignorado"
        elif jw and "MUBI" in jw["servicos"]:
            cat.adicionar("MUBI", jw, "adicionado_justwatch", "kubi2021/plugin.video.mubi + JustWatch")
            linha["resultado"] = "adicionado_justwatch"
        else:
            info = jw or {"jw_id": f"mubi{m['mubi_id']}", "imdb_id": imdb, "titulo_pt": m["title"],
                          "titulo_original": m.get("original_title") or m["title"], "ano": m.get("year") or "",
                          "duracao_min": m.get("duration") or "", "saidas": None}
            if jw:
                info = {**jw, "imdb_id": imdb}
            cat.adicionar("MUBI", info, "adicionado_kubi", "kubi2021/plugin.video.mubi (BR live)")
            linha["resultado"] = "adicionado_kubi"
        res.append(linha)
        print(f"  {linha['resultado']:22} {linha['titulo']} ({linha['ano']})", flush=True)

    # 2) no catálogo da MUBI e o kubi diz que não está disponível
    fora = [f for f in cat.linhas if cat.tem(f, "MUBI") and f["imdb_id"] not in vivos]
    jw = ofertas_jw([f["jw_id"] for f in fora])
    for f in list(fora):
        r = jw.get(f["jw_id"])
        linha = {"servico": "MUBI", "sentido": "catalogo_sem_kubi", "imdb_id": f["imdb_id"],
                 "titulo": f["titulo_original"], "ano": f["ano"]}
        if r and "MUBI" in r["servicos"]:
            linha["resultado"] = "divergencia_justwatch_mantem"
        elif f["jw_id"].isdigit():
            cat.remover(f, "MUBI", "removido_kubi", "kubi2021/plugin.video.mubi + JustWatch sem oferta")
            linha["resultado"] = "removido_kubi"
        else:
            linha["resultado"] = "divergencia_sem_jw"
        res.append(linha)
    cat.salvar()
    print("Resultado:", gravar_resultado("mubi", res, ["servico", "sentido", "resultado", "imdb_id", "titulo", "ano"]))
    for sentido in ("kubi_sem_catalogo", "catalogo_sem_kubi"):
        cont = {}
        for l in res:
            if l["sentido"] == sentido:
                cont[l["resultado"]] = cont.get(l["resultado"], 0) + 1
        print(f"  {sentido}: {cont}")


def saidas(anterior):
    cat, res = Catalogo(), []
    with open(anterior, encoding="utf-8") as fh:
        antes = list(csv.DictReader(fh))
    with open("data/sairam.csv", encoding="utf-8") as fh:
        sairam = list(csv.DictReader(fh))

    def linha_antes(s):
        for f in antes:
            if s["servico"] in f["servicos"].split("|") and (
                    (s["imdb_id"] and f["imdb_id"] == s["imdb_id"]) or
                    (not s["imdb_id"] and f["titulo_original"].strip() == s["titulo_original"] and f["ano"] == s["ano"])):
                return f

    origens = {id(s): linha_antes(s) for s in sairam}
    jw = ofertas_jw([f["jw_id"] for f in origens.values() if f])
    for s in sairam:
        serv, f = s["servico"], origens[id(s)]
        linha = dict(s)
        r = jw.get(f["jw_id"]) if f else None
        if not (r and serv in r["servicos"]):
            # o mesmo filme pode ter outro objeto no JustWatch
            # exige o mesmo IMDb ID ou, sem IMDb, o mesmo título exato
            alt = [c for c in buscar_jw(s["titulo_original"], s["ano"])
                   if serv in c["servicos"] and (c["imdb_id"] == s["imdb_id"] if s["imdb_id"]
                                                 else norm(s["titulo_original"]) in map(norm, c["titulos"]))]
            r = alt[0] if alt else r
        if r and serv in r["servicos"]:
            if r["duracao_min"] and int(r["duracao_min"]) < DURACAO_MIN:
                linha["resultado"] = "curta_agora"
            else:
                info = {**f, **{k: v for k, v in r.items() if v not in ("", None)}} if f else r
                if s["imdb_id"]:
                    info["imdb_id"] = s["imdb_id"]
                cat.adicionar(serv, info, "restaurado_saida_falsa", "JustWatch (consulta direta)")
                linha["resultado"] = "saida_falsa_restaurada"
        else:
            linha["resultado"] = "saida_confirmada"
        res.append(linha)
    cat.salvar()
    print("Resultado:", gravar_resultado("saidas", res, ["imdb_id", "titulo_original", "ano", "servico", "resultado"]))
    contar(res)


def amostra(n=25):
    cat, res = Catalogo(), []
    sorteados = []
    for s in ORDEM:
        com = [f for f in cat.linhas if cat.tem(f, s) and f["jw_id"].isdigit()]
        for f in random.Random(f"{HOJE}-{s}").sample(com, min(n, len(com))):
            sorteados.append((s, f))
    jw = ofertas_jw([f["jw_id"] for _, f in sorteados])
    for s, f in sorteados:
        r = jw.get(f["jw_id"])
        res.append({"servico": s, "jw_id": f["jw_id"], "imdb_id": f["imdb_id"],
                    "titulo_original": f["titulo_original"].strip(), "ano": f["ano"],
                    "servicos_catalogo": f["servicos"],
                    "servicos_justwatch": "|".join(x for x in ORDEM if r and x in r["servicos"]),
                    "bate": "sim" if r and s in r["servicos"] else "nao"})
    print("Resultado:", gravar_resultado("amostra", res, list(res[0])))
    for s in ORDEM:
        do_serv = [r for r in res if r["servico"] == s]
        print(f"  {s:12} {sum(r['bate'] == 'sim' for r in do_serv)} de {len(do_serv)} batem")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"chegadas": chegadas, "mubi": mubi, "saidas": saidas,
     "amostra": lambda *a: amostra(int(a[0]) if a else 25)}[cmd](*args)
