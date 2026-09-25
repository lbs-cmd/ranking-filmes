"""Etapa 3: top 500 pela nota do Letterboxd (mínimo de 1.000 avaliações)."""
import csv
import re

MIN_AVALIACOES, TOP = 1000, 500


def limpar(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


def main():
    with open("data/catalogo.csv", encoding="utf-8") as fh:
        cat = {}
        for f in csv.DictReader(fh):
            cat.setdefault(f["imdb_id"], f)
    with open("data/letterboxd.csv", encoding="utf-8") as fh:
        lb = [r for r in csv.DictReader(fh) if int(r["avaliacoes_letterboxd"]) >= MIN_AVALIACOES]
    lb.sort(key=lambda r: (-float(r["nota_letterboxd"]), -int(r["avaliacoes_letterboxd"])))
    campos = ["posicao", "titulo_original", "titulo_pt", "ano", "diretor", "duracao_min",
              "nota_letterboxd", "avaliacoes_letterboxd", "imdb_id", "servicos"]
    with open("data/top500.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, campos, extrasaction="ignore")
        w.writeheader()
        for pos, r in enumerate(lb[:TOP], 1):
            f = {**cat[r["imdb_id"]], **r, "posicao": pos}
            for k in ("titulo_original", "titulo_pt", "diretor"):
                f[k] = limpar(f[k])
            w.writerow(f)
    print(f"Elegíveis (>= {MIN_AVALIACOES} avaliações): {len(lb)} | gravados: {min(TOP, len(lb))}")


if __name__ == "__main__":
    main()
