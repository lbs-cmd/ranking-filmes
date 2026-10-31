"""Lê uma lista mensal de saídas do RendaGeek e grava os itens em JSON.

Uso: python3 scripts/rendageek.py <url> <saida.json> [serviço]
Formatos aceitos: "Título (ano) — D de mês" (o ano pode faltar) e, desde nov/2026,
"D de mês: Título (ano); Título (ano)."
A leitura para na seção de destaques ("Quais são os principais..."), que repete itens.
Sai com código 2 se a página não existir (404).
"""
import html, json, re, sys, urllib.error, urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
MESES = {m: i for i, m in enumerate(
    ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
     "setembro", "outubro", "novembro", "dezembro"], 1)}
LINHA = re.compile(r"(.+?)\s*(?:\((\d{4})\))?\s*[—–]\s*(\d{1,2})º?\s+de\s+(" + "|".join(MESES) + r")$")
# formato desde nov/2026: "D de mês: Título (ano); Título (ano)."
DIA = re.compile(r"(\d{1,2})º?\s+de\s+(" + "|".join(MESES) + r"):\s*(.+)$")
ITEM = re.compile(r"\s*(.+?)\s*\((\d{4})\)\s*[;.]?")


def main(url, saida, servico="Netflix"):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        pagina = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(f"{url}: HTTP {e.code}")
        sys.exit(2 if e.code == 404 else 1)
    ano_lista = int(re.search(r"de-(\d{4})", url).group(1))
    m = re.search(r"<article.*?</article>", pagina, re.S)
    texto = re.sub(r"<(script|style).*?</\1>", "", m.group(0) if m else pagina, flags=re.S)
    texto = re.sub(r"<br\s*/?>|</(p|li|h\d)>", "\n", texto)
    texto = html.unescape(re.sub(r"<[^>]+>", "", texto)).split("Quais são os principais")[0]
    itens = []
    for linha in texto.split("\n"):
        d = DIA.match(linha.strip())
        if d:
            for t in ITEM.finditer(d[3]):
                itens.append({"titulo": t[1].strip(), "ano": int(t[2]),
                              "data": f"{ano_lista}-{MESES[d[2]]:02d}-{int(d[1]):02d}",
                              "servico": servico, "fonte": "RendaGeek", "url": url})
            continue
        m = LINHA.match(linha.strip())
        if m:
            itens.append({"titulo": m[1].strip(), "ano": int(m[2]) if m[2] else None,
                          "data": f"{ano_lista}-{MESES[m[4]]:02d}-{int(m[3]):02d}",
                          "servico": servico, "fonte": "RendaGeek", "url": url})
    with open(saida, "w", encoding="utf-8") as fh:
        json.dump(itens, fh, ensure_ascii=False, indent=1)
    datas = sorted(i["data"] for i in itens)
    print(f"{url}: {len(itens)} itens" + (f" ({datas[0]} a {datas[-1]})" if datas else ""))


if __name__ == "__main__":
    main(*sys.argv[1:])
