"""Etapa 1: catálogo de filmes por assinatura (flatrate) no JustWatch BR."""
import csv, json, time, urllib.request
from collections import Counter

API = "https://apis.justwatch.com/graphql"
# código JustWatch -> nome do serviço (variantes contam como o serviço principal)
SERVICOS = {
    "nfx": "Netflix", "nfa": "Netflix",
    "prv": "Prime Video",
    "mxx": "HBO Max",
    "dnp": "Disney+",
    "pmp": "Paramount+", "ppp": "Paramount+",
    "mbi": "MUBI",
}
CONSULTAR = ["nfx", "prv", "mxx", "dnp", "pmp", "mbi"]
DURACAO_MIN = 40

Q = """query($after:String,$pkg:[String!],$y0:Int,$y1:Int){
 popularTitles(country:BR,first:100,after:$after,
  filter:{packages:$pkg,objectTypes:[MOVIE],monetizationTypes:[FLATRATE],
          releaseYear:{min:$y0,max:$y1}}){
  totalCount pageInfo{hasNextPage endCursor}
  edges{node{objectId
   content(country:BR,language:"pt"){title originalTitle originalReleaseYear runtime
     externalIds{imdbId} scoring{imdbScore imdbVotes}}
   offers(country:BR,platform:WEB){monetizationType package{shortName}}}}}}"""


def gql(variables):
    body = json.dumps({"query": Q, "variables": variables}).encode()
    for tentativa in range(5):
        try:
            req = urllib.request.Request(API, body, {"content-type": "application/json",
                                                    "user-agent": "Mozilla/5.0"})
            d = json.load(urllib.request.urlopen(req, timeout=60))
            if "errors" in d:
                raise RuntimeError(d["errors"])
            return d["data"]["popularTitles"]
        except Exception as e:
            print("  erro:", e, "- tentando de novo")
            time.sleep(5 * (tentativa + 1))
    raise SystemExit("JustWatch falhou 5 vezes")


def buscar(pkg, y0=None, y1=None):
    """Pagina uma consulta; se a paginação parar antes do total, divide por anos."""
    nos, after, total = [], None, None
    while True:
        r = gql({"after": after, "pkg": [pkg], "y0": y0, "y1": y1})
        if total is None:  # após ~1900 itens o JW devolve totalCount=0
            total = r["totalCount"]
        nos += [e["node"] for e in r["edges"]]
        if not r["pageInfo"]["hasNextPage"] or not r["edges"]:
            break
        after = r["pageInfo"]["endCursor"]
        time.sleep(0.3)
    if len(nos) < total:
        a, b = (y0 or 1890), (y1 or 2030)
        if a == b:
            print(f"  aviso: {pkg} {a}: só {len(nos)}/{total}")
            return nos
        m = (a + b) // 2
        return buscar(pkg, a, m) + buscar(pkg, m + 1, b)
    return nos


def main():
    filmes = {}
    for pkg in CONSULTAR:
        nos = buscar(pkg)
        print(f"{SERVICOS[pkg]}: {len(nos)} títulos retornados")
        for n in nos:
            c = n["content"]
            servs = {SERVICOS[o["package"]["shortName"]] for o in n["offers"] or []
                     if o["monetizationType"] == "FLATRATE" and o["package"]["shortName"] in SERVICOS}
            servs.add(SERVICOS[pkg])
            f = filmes.setdefault(n["objectId"], {
                "jw_id": n["objectId"], "titulo_pt": c["title"],
                "titulo_original": c["originalTitle"] or c["title"],
                "ano": c["originalReleaseYear"] or "", "duracao_min": c["runtime"] or "",
                "imdb_id": (c["externalIds"] or {}).get("imdbId") or "",
                "imdb_nota": (c["scoring"] or {}).get("imdbScore") or "",
                "imdb_votos": (c["scoring"] or {}).get("imdbVotes") or "",
                "servicos": set()})
            f["servicos"] |= servs

    # junta duplicatas com o mesmo IMDb ID (títulos distintos no JustWatch)
    por_imdb = {}
    for f in list(filmes.values()):
        if f["imdb_id"]:
            if f["imdb_id"] in por_imdb:
                por_imdb[f["imdb_id"]]["servicos"] |= f["servicos"]
                del filmes[f["jw_id"]]
            else:
                por_imdb[f["imdb_id"]] = f

    curtas = [k for k, f in filmes.items() if f["duracao_min"] != "" and f["duracao_min"] < DURACAO_MIN]
    for k in curtas:
        del filmes[k]
    sem_duracao = sum(1 for f in filmes.values() if f["duracao_min"] == "")

    ordem = ["Netflix", "Prime Video", "HBO Max", "Disney+", "Paramount+", "MUBI"]
    campos = ["jw_id", "titulo_pt", "titulo_original", "ano", "duracao_min",
              "imdb_id", "imdb_nota", "imdb_votos", "servicos"]
    with open("data/catalogo.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, campos)
        w.writeheader()
        for f in sorted(filmes.values(), key=lambda f: (str(f["titulo_original"]).lower())):
            w.writerow({**f, "servicos": "|".join(s for s in ordem if s in f["servicos"])})

    cont = Counter(s for f in filmes.values() for s in f["servicos"])
    print(f"\nCurtas descartados (< {DURACAO_MIN} min): {len(curtas)}")
    print(f"Sem duração informada (mantidos): {sem_duracao}")
    print(f"Filmes únicos: {len(filmes)}  (com IMDb ID: {sum(1 for f in filmes.values() if f['imdb_id'])})")
    for s in ordem:
        print(f"  {s:12} {cont[s]}")


if __name__ == "__main__":
    main()
