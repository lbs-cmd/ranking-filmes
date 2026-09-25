"""Etapa 3: top 500 pela nota do Letterboxd (mínimo de 1.000 avaliações)."""
import csv

MIN_AVALIACOES, TOP = 1000, 500


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
            w.writerow({**cat[r["imdb_id"]], **r, "posicao": pos})
    print(f"Elegíveis (>= {MIN_AVALIACOES} avaliações): {len(lb)} | gravados: {min(TOP, len(lb))}")


if __name__ == "__main__":
    main()
