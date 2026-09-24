"""
cep_api.py — Análise de distância aluno↔escola por CEP
=============================================================================
Portado de AUTO_SERE/CEP.py para src/comum/cep_api.py.

Para cada aluno em alunos.json, geocodifica o CEP (via AwesomeAPI, com
fallback ViaCEP+Nominatim quando a coordenada parece genérica ou a
consulta falha) e calcula a distância até a escola, sinalizando quem está
fora do raio configurado. Gera alunos_fora_raio.json/.xlsx e
alunos_coordenadas.json; alunos transferidos (via turmas.json) e nomes
duplicados são ignorados.

MUDANÇAS EM RELAÇÃO AO ORIGINAL:

1. CEP_ESCOLA: antes uma constante fixa ("84016630") no topo do módulo.
   Decisão do usuário (03/09/2026): vem de
   src.comum.configuracao.unidade_escolar() — o CEP que o usuário digita
   manualmente no setup (o nome e endereço da escola vêm de um seletor
   pesquisável populado por src.automacao.coleta_emails, que raspa todas
   as escolas do município; o CEP não é extraído desse texto — é
   informado à parte, ver src.comum.configuracao.definir_unidade_escolar).

2. Caminhos: BASE/SERE/CAMINHO_ALUNOS/CAMINHO_TURMAS/CAMINHO_ERROS (antes
   fixos, servidor Linux) agora vêm de src.comum.paths.dados_ano_atual()
   — mesma arquitetura dos demais scripts já portados. Os arquivos de
   saída (alunos_fora_raio.json/.xlsx, alunos_coordenadas.json) também
   vão para essa mesma pasta, em vez de "ao lado de alunos.json"
   (equivalente na prática, já que alunos.json também está lá).

3. Todo o corpo principal (antes rodando solto no nível do módulo, sem
   função nem `if __name__ == "__main__":` — ver docstring do original,
   que já sinalizava isso como um problema real) foi envolvido em
   executar_analise_distancia(raio_km=2.0, analise_codigo=False) — decisão
   do usuário (03/09/2026, mesmo padrão de outros scripts): pronta para
   ser chamada por um futuro botão de GUI, sem efeito colateral ao
   importar o módulo.

4. cache_coords/coords_usadas/erros_cep_lista: permanecem globais do
   módulo (decisão do usuário — cache PERSISTE entre chamadas de
   executar_analise_distancia() na mesma sessão de processo, para deixar
   re-análises mais rápidas), mas agora com uma função nova,
   limpar_cache_geocodificacao(), para resetar manualmente quando o
   usuário perceber divergência (ex.: um CEP mudou de coordenada, ou
   houve falso positivo de "coordenada genérica").

5. import datetime: o original tinha um bug documentado (ano_atual()
   chamava datetime.now() sem o import correspondente — NameError
   garantido). O CÓDIGO REAL já trazia `from datetime import datetime,
   timedelta` no bloco de imports (a docstring do script estava
   desatualizada em relação ao próprio código) — de qualquer forma, este
   módulo usa exclusivamente src.comum.paths.ano_atual() (já testada e em
   uso por todos os outros módulos), então esse ponto nem se aplica mais
   aqui.

Toda a lógica de negócio (cascata de geocodificação, detecção de
coordenada genérica por igualdade de 4 casas decimais entre CEPs
diferentes, retry com backoff exponencial em timeout, filtro de
transferidos/duplicados, ordenação por distância decrescente, geração do
Excel) é idêntica ao original — nenhuma regra foi alterada.

Uso:
    from src.comum.cep_api import executar_analise_distancia

    resultado = executar_analise_distancia(raio_km=2.0)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from openpyxl import Workbook
from openpyxl.styles import Font

from src.comum import paths as _paths
from src.comum.configuracao import unidade_escolar

_DADOS = _paths.dados_ano_atual()

CAMINHO_ALUNOS = _DADOS / "alunos.json"
CAMINHO_TURMAS = _DADOS / "turmas.json"
CAMINHO_ERROS  = _DADOS / "alunos_erros.json"

RAIO_KM_PADRAO = 2.0

# ─────────────────────────────────────────────────────────────────────────────
# DETECÇÃO DE COORDENADA GENÉRICA
# A AwesomeAPI às vezes retorna o centróide da cidade inteira quando não tem
# coordenadas exatas para o CEP. Isso gera distâncias falsas (≈5 km).
# Estratégia: se dois CEPs diferentes retornarem a MESMA lat/lng com precisão
# de 4 casas decimais, o segundo é tratado como genérico e descartado.
#
# cache_coords/coords_usadas/erros_cep_lista permanecem globais do módulo
# (decisão do usuário, 03/09/2026): o cache PERSISTE entre chamadas de
# executar_analise_distancia() na mesma sessão de processo, deixando
# re-análises mais rápidas. Use limpar_cache_geocodificacao() para resetar
# manualmente em caso de divergência percebida.
# ─────────────────────────────────────────────────────────────────────────────
cache_coords: dict[str, tuple[float, float]] = {}    # cep → (lat, lng) coords validadas
coords_usadas: dict[tuple[float, float], str] = {}   # (lat4, lng4) → cep primeiro CEP que usou essa coord
erros_cep_lista: list[dict] = []


def limpar_cache_geocodificacao() -> None:
    """
    Zera o cache de coordenadas (cache_coords, coords_usadas) e a lista de
    erros de CEP acumulada. Chame antes de executar_analise_distancia()
    quando desconfiar que o cache está retendo coordenadas desatualizadas
    ou falsos positivos de "coordenada genérica" — decisão do usuário
    (03/09/2026, para complementar o cache persistente entre execuções).
    """
    cache_coords.clear()
    coords_usadas.clear()
    erros_cep_lista.clear()


def _coord_chave(lat, lng) -> tuple[float, float]:
    """Chave de comparação com 4 casas decimais (~11 m de precisão)."""
    return (round(float(lat), 4), round(float(lng), 4))


def _coord_e_generica(lat, lng, cep: str) -> bool:
    """
    Retorna True se a coordenada parecer ser um centróide genérico de cidade.
    Critério: já foi retornada por um CEP DIFERENTE anteriormente.
    """
    chave = _coord_chave(lat, lng)
    cep_anterior = coords_usadas.get(chave)
    if cep_anterior is not None and cep_anterior != cep:
        return True
    coords_usadas[chave] = cep
    return False


def _tentar_nominatim(cep: str, nome_aluno: str) -> Optional[tuple[float, float]]:
    """
    Tenta obter coordenadas via ViaCEP (logradouro) + Nominatim.
    Retorna (lat, lng) ou None.
    """
    try:
        r = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=10)
        if r.status_code != 200:
            return None
        dados = r.json()
        if dados.get("erro"):
            return None

        logradouro = dados.get("logradouro", "")
        bairro     = dados.get("bairro", "")
        localidade = dados.get("localidade", "")
        uf         = dados.get("uf", "")

        if not localidade:
            return None

        # Monta endereço do mais específico para o mais genérico
        candidatos = []
        if logradouro:
            candidatos.append(f"{logradouro}, {bairro}, {localidade}, {uf}, Brasil")
        if bairro:
            candidatos.append(f"{bairro}, {localidade}, {uf}, Brasil")
        candidatos.append(f"{localidade}, {uf}, Brasil")

        geolocator = Nominatim(user_agent="geocep_judith_v3")
        for endereco in candidatos:
            try:
                loc = geolocator.geocode(endereco, timeout=10)
                if loc and loc.latitude is not None:
                    lat, lng = loc.latitude, loc.longitude
                    # Ainda verifica se essa coord também é genérica
                    if not _coord_e_generica(lat, lng, cep):
                        print(f"   ✅ Nominatim OK para CEP {cep}: {endereco[:60]}")
                        return (lat, lng)
                time.sleep(1)  # respeita rate limit do Nominatim
            except Exception:
                time.sleep(1)
                continue

    except Exception as e:
        print(f"   ⚠️ Erro ViaCEP/Nominatim para CEP {cep}: {e}")

    return None


def cep_para_coords(
    cep: str, nome_aluno: str = "", tentativa: int = 1, max_tentativas: int = 3
) -> Optional[tuple[float, float]]:
    """
    Converte CEP em coordenadas.
    Fluxo:
      1. Cache local
      2. AwesomeAPI  → valida se coord não é genérica
      3. Fallback: ViaCEP + Nominatim
      4. Se tudo falhar → registra erro e retorna None
    """
    cep = cep.replace("-", "").strip()

    if len(cep) != 8 or not cep.isdigit():
        print(f"⚠️ CEP inválido: {cep}")
        if nome_aluno:
            erros_cep_lista.append({"nome": nome_aluno, "cep": cep, "erro": "CEP inválido"})
        return None

    if cep in cache_coords:
        return cache_coords[cep]

    # ── 1. AwesomeAPI ────────────────────────────────────────────────────────
    try:
        url      = f"https://cep.awesomeapi.com.br/json/{cep}"
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            dados = response.json()
            lat   = dados.get("lat")
            lng   = dados.get("lng")

            if lat and lng:
                if _coord_e_generica(lat, lng, cep):
                    # Coordenada genérica detectada → tenta Nominatim
                    print(f"⚠️ {nome_aluno} - CEP {cep}: coordenada genérica detectada, tentando Nominatim...")
                    coords = _tentar_nominatim(cep, nome_aluno)
                    if coords:
                        cache_coords[cep] = coords
                        return coords
                    # Nominatim também falhou → registra como erro
                    if nome_aluno:
                        erros_cep_lista.append({
                            "nome": nome_aluno,
                            "cep": cep,
                            "erro": "Coordenada genérica da API, Nominatim sem resultado",
                        })
                    return None
                else:
                    coords = (float(lat), float(lng))
                    cache_coords[cep] = coords
                    return coords
            else:
                # API não retornou coords → tenta Nominatim diretamente
                print(f"⚠️ {nome_aluno} - CEP {cep} sem coordenadas na AwesomeAPI, tentando Nominatim...")
                coords = _tentar_nominatim(cep, nome_aluno)
                if coords:
                    cache_coords[cep] = coords
                    return coords
                if nome_aluno:
                    erros_cep_lista.append({
                        "nome": nome_aluno,
                        "cep": cep,
                        "erro": "API não retornou coordenadas e Nominatim falhou",
                    })
                return None

        else:
            print(f"⚠️ CEP {cep} - Status {response.status_code}")
            # Tenta Nominatim como fallback de status != 200
            coords = _tentar_nominatim(cep, nome_aluno)
            if coords:
                cache_coords[cep] = coords
                return coords
            if nome_aluno:
                erros_cep_lista.append({
                    "nome": nome_aluno,
                    "cep": cep,
                    "erro": f"AwesomeAPI status {response.status_code}",
                })
            return None

    except requests.exceptions.Timeout:
        if tentativa < max_tentativas:
            pausa = 2 ** tentativa
            print(f"⏱️ Timeout CEP {cep} - aguardando {pausa}s...")
            time.sleep(pausa)
            return cep_para_coords(cep, nome_aluno, tentativa + 1)
        else:
            print(f"❌ Timeout definitivo para CEP {cep}, tentando Nominatim...")
            coords = _tentar_nominatim(cep, nome_aluno)
            if coords:
                cache_coords[cep] = coords
                return coords
            if nome_aluno:
                erros_cep_lista.append({"nome": nome_aluno, "cep": cep, "erro": "Timeout API"})
            return None

    except Exception as e:
        print(f"❌ Erro ao consultar CEP {cep}: {e}")
        coords = _tentar_nominatim(cep, nome_aluno)
        if coords:
            cache_coords[cep] = coords
            return coords
        if nome_aluno:
            erros_cep_lista.append({"nome": nome_aluno, "cep": cep, "erro": str(e)})
        return None


def executar_analise_distancia(raio_km: float = RAIO_KM_PADRAO, analise_codigo: bool = False) -> dict:
    """
    Executa a análise completa de distância aluno↔escola: geocodifica o
    CEP da escola (via src.comum.configuracao.unidade_escolar()) e o de
    cada aluno em alunos.json, calcula a distância, sinaliza quem está
    fora de `raio_km`, e salva alunos_fora_raio.json/.xlsx e
    alunos_coordenadas.json em dados/<ano>/.

    Renomeada/extraída do corpo solto no nível do módulo do CEP.py
    original — decisão do usuário (03/09/2026): pronta para ser chamada
    por um futuro botão de GUI, sem efeito colateral ao importar o
    módulo.

    Levanta ValueError se a unidade escolar ainda não estiver configurada
    (nome+endereço+CEP — ver src.comum.configuracao.definir_unidade_escolar)
    ou se não for possível geocodificar o CEP da escola. Levanta
    FileNotFoundError se alunos.json não existir.

    Retorna um resumo (dict) com as contagens finais.
    """
    print("🏫 Análise de Distância\n")
    print("=" * 50)

    dados_unidade = unidade_escolar()
    if not dados_unidade or not dados_unidade.get("cep"):
        raise ValueError(
            "A unidade escolar ainda não foi configurada com CEP "
            "(ver src.comum.configuracao.definir_unidade_escolar). "
            "Rode o setup inicial (escolha da escola + CEP) antes de analisar distâncias."
        )
    cep_escola = dados_unidade["cep"]

    # 1. Obtém coordenadas da escola
    print(f"📍 Buscando coordenadas da escola (CEP: {cep_escola})...")
    coord_escola = cep_para_coords(cep_escola)
    if not coord_escola:
        raise ValueError("❌ Não foi possível obter as coordenadas da escola.")
    print(f"✅ Coordenadas da escola: {coord_escola}\n")

    # 2. Carrega lista de alunos transferidos
    print("📋 Carregando lista de transferidos...")
    try:
        with open(CAMINHO_TURMAS, "r", encoding="utf-8") as f:
            turmas = json.load(f)

        cgms_transferidos = set()
        if isinstance(turmas, dict):
            for turma_nome, alunos_turma in turmas.items():
                if isinstance(alunos_turma, list):
                    for aluno in alunos_turma:
                        if isinstance(aluno, dict):
                            cgm      = (aluno.get("CGM") or aluno.get("Cgm") or "").strip()
                            situacao = (aluno.get("Situação", "") or
                                        aluno.get("SituaÃ§Ã£o", "") or
                                        aluno.get("Situacao", ""))
                            if cgm and situacao and situacao.strip().lower() in ["transferido", "transferida"]:
                                cgms_transferidos.add(cgm)

        print(f"✅ {len(cgms_transferidos)} CGMs transferidos encontrados\n")

    except FileNotFoundError:
        print(f"⚠️ Arquivo {CAMINHO_TURMAS} não encontrado. Continuando sem filtro.\n")
        cgms_transferidos = set()
    except Exception as e:
        print(f"❌ Erro ao ler turmas: {e}\n   Continuando sem filtro.\n")
        cgms_transferidos = set()

    # 3. Carrega lista de alunos
    print("📚 Carregando lista de alunos...")
    try:
        with open(CAMINHO_ALUNOS, "r", encoding="utf-8") as f:
            alunos = json.load(f)
        print(f"✅ {len(alunos)} registros carregados\n")
    except FileNotFoundError:
        raise FileNotFoundError(f"❌ Arquivo {CAMINHO_ALUNOS} não encontrado.")
    except Exception as e:
        raise ValueError(f"❌ Erro ao ler alunos: {e}")

    # 4. Processa alunos
    print("=" * 50)
    print(f"🔍 Processando alunos (raio: {raio_km} km)...\n")

    nomes_processados         = set()
    alunos_fora_raio          = []
    alunos_processados_coords = []
    contador                  = 0
    erros_cep                 = 0
    ignorados_transferidos    = 0
    ignorados_duplicados      = 0

    for aluno in alunos:
        nome    = aluno.get("Nome", "").strip().upper()
        cgm     = aluno.get("CGM", "").strip()
        cep_raw = aluno.get("CEP", "").replace("CEP :", "").replace("CEP:", "").strip()

        if not nome:
            continue

        if nome in nomes_processados:
            ignorados_duplicados += 1
            continue

        if cgm in cgms_transferidos:
            print(f"🚫 Ignorado (transferido): {nome} (CGM {cgm})")
            ignorados_transferidos += 1
            continue

        nomes_processados.add(nome)

        if not cep_raw:
            print(f"⚠️ {nome} - Sem CEP")
            erros_cep += 1
            erros_cep_lista.append({"nome": nome, "cep": "", "erro": "CEP não informado"})
            continue

        coord_aluno = cep_para_coords(cep_raw, nome)
        if not coord_aluno:
            print(f"⚠️ {nome} - CEP {cep_raw} não localizado")
            erros_cep += 1
            continue

        distancia_km = geodesic(coord_escola, coord_aluno).km
        contador += 1

        print(f"✓ {nome} → CEP {cep_raw} → {distancia_km:.2f} km")

        alunos_processados_coords.append({
            "nome":         nome,
            "cgm":          cgm,
            "cep":          cep_raw,
            "latitude":     coord_aluno[0],
            "longitude":    coord_aluno[1],
            "distancia_km": round(distancia_km, 2),
        })

        if distancia_km > raio_km:
            alunos_fora_raio.append({
                "nome":         nome,
                "cgm":          cgm,
                "cep":          cep_raw,
                "distancia_km": round(distancia_km, 2),
                "coordenadas": {
                    "latitude":  coord_aluno[0],
                    "longitude": coord_aluno[1],
                },
            })

        if contador % 10 == 0:
            print(f"\n📊 Progresso: {contador} alunos processados...\n")

        time.sleep(1.5)

    # 5. Ordena por distância (maior primeiro)
    alunos_fora_raio.sort(key=lambda x: x["distancia_km"], reverse=True)

    # 6. Salva arquivos
    print("\n" + "=" * 50)
    print("💾 Salvando arquivos...\n")

    arquivo_json   = _DADOS / "alunos_fora_raio.json"
    arquivo_excel  = _DADOS / "alunos_fora_raio.xlsx"
    arquivo_coords = _DADOS / "alunos_coordenadas.json"

    try:
        with open(arquivo_json, "w", encoding="utf-8") as f:
            json.dump({
                "metadados": {
                    "data_analise": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "cep_escola": cep_escola,
                    "coordenadas_escola": {
                        "latitude":  coord_escola[0],
                        "longitude": coord_escola[1],
                    },
                    "raio_km": raio_km,
                    "total_alunos_processados": contador,
                    "total_fora_raio": len(alunos_fora_raio),
                },
                "alunos": alunos_fora_raio,
            }, f, ensure_ascii=False, indent=2)
        print(f"✅ JSON salvo: {arquivo_json}")
    except Exception as e:
        print(f"❌ Erro ao salvar JSON: {e}")

    if erros_cep_lista:
        try:
            with open(CAMINHO_ERROS, "w", encoding="utf-8") as f:
                json.dump({
                    "data_analise": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_erros": len(erros_cep_lista),
                    "erros": erros_cep_lista,
                }, f, ensure_ascii=False, indent=2)
            print(f"✅ JSON de erros salvo: {CAMINHO_ERROS}")
        except Exception as e:
            print(f"❌ Erro ao salvar JSON de erros: {e}")

    try:
        with open(arquivo_coords, "w", encoding="utf-8") as f:
            json.dump({
                "metadados": {
                    "data_analise": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "total_alunos_com_coordenadas": len(alunos_processados_coords),
                },
                "alunos": alunos_processados_coords,
            }, f, ensure_ascii=False, indent=2)
        print(f"✅ JSON com coordenadas salvo: {arquivo_coords}")
    except Exception as e:
        print(f"❌ Erro ao salvar JSON de coordenadas: {e}")

    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "Alunos fora do raio"

        headers = ["Nome", "CEP", "Distância (km)"]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)

        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 12
        ws.column_dimensions['C'].width = 15

        for a in alunos_fora_raio:
            ws.append([a["nome"], a["cep"], a["distancia_km"]])

        wb.save(arquivo_excel)
        print(f"✅ Excel salvo: {arquivo_excel}")
    except Exception as e:
        print(f"❌ Erro ao salvar Excel: {e}")

    # 7. Estatísticas finais
    print("\n" + "=" * 50)
    print("📈 ESTATÍSTICAS FINAIS\n")
    print(f"   Total de registros no arquivo:      {len(alunos)}")
    print(f"   Alunos transferidos (ignorados):    {ignorados_transferidos}")
    print(f"   Nomes duplicados (ignorados):       {ignorados_duplicados}")
    print(f"   Alunos com erro de CEP:             {erros_cep}")
    print(f"   Alunos processados com sucesso:     {contador}")
    print(f"   Alunos FORA do raio de {raio_km} km:     {len(alunos_fora_raio)}")

    resumo = {
        "total_registros": len(alunos),
        "ignorados_transferidos": ignorados_transferidos,
        "ignorados_duplicados": ignorados_duplicados,
        "erros_cep": erros_cep,
        "processados": contador,
        "fora_do_raio": len(alunos_fora_raio),
    }

    if alunos_fora_raio:
        distancias = [a["distancia_km"] for a in alunos_fora_raio]
        print(f"\n   Distância mínima: {min(distancias):.2f} km")
        print(f"   Distância máxima: {max(distancias):.2f} km")
        print(f"   Distância média:  {sum(distancias)/len(distancias):.2f} km")
        resumo["distancia_minima_km"] = round(min(distancias), 2)
        resumo["distancia_maxima_km"] = round(max(distancias), 2)
        resumo["distancia_media_km"] = round(sum(distancias) / len(distancias), 2)

    print("\n" + "=" * 50)
    print("✅ Análise concluída com sucesso!")
    print("=" * 50)

    return resumo


if __name__ == "__main__":
    executar_analise_distancia()
