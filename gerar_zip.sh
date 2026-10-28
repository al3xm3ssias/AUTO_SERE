#!/bin/bash

PASTA="$(pwd)"
NOME="$(basename "$PASTA")"

ZIP="${NOME}.zip"
MAPA="${NOME}_MAPA.txt"

echo "======================================"
echo " Gerando pacote: $NOME"
echo "======================================"

# Remove arquivos antigos
rm -f "$ZIP" "$MAPA"

echo
echo "[1/4] Identificando arquivos..."

ARQUIVOS=$(git ls-files -co --exclude-standard | grep -v "^${MAPA}$" | grep -v "^${ZIP}$")

echo "$ARQUIVOS" > "$MAPA"

echo "Mapa criado: $MAPA"
echo "Arquivos encontrados: $(wc -l < "$MAPA")"

echo
echo "[2/4] Criando ZIP..."

# Criar ZIP usando a lista de arquivos
echo "$ARQUIVOS" | zip -q "$ZIP" -@

echo
echo "[3/4] Conferindo ZIP..."

echo
echo "Conteúdo do ZIP:"
unzip -l "$ZIP"

echo
echo "[4/4] Concluído!"
echo
echo "======================================"
echo " ZIP : $ZIP"
echo " MAPA: $MAPA"
echo "======================================"
echo
echo "Quantidade de arquivos:"
wc -l < "$MAPA"

echo
echo "Tamanho do ZIP:"
du -h "$ZIP"
