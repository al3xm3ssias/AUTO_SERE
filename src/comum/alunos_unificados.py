"""
alunos_unificados.py — visão conjunta de alunos.json (básico) e alunos_completo.json (completo)
================================================================================================

Os dois arquivos descrevem o MESMO aluno com nomes de campo diferentes:

  * ``alunos.json``          lista de dicts com rótulos do SERE ("Nome", "Data Nascimento", "Mãe"...),
                             coletada pela tela de consulta (``src.automacao.alunos``).
  * ``alunos_completo.json`` dict ``{cgm: {...}}`` com chaves em snake_case ("nome", "nome_mae"...),
                             coletado pela tela de edição (``src.automacao.alunos_completo``), com ~60
                             campos a mais (certidão, família, socioeconômico, deficiências...).

Este módulo junta os dois pelo CGM, sem alterar nenhum arquivo:

  1. Os campos do cadastro básico continuam como estão (mesmos rótulos), para o resto do sistema.
  2. Campo básico VAZIO que o completo tem preenchido é completado (e marcado em ``_preenchido_completo``).
  3. Campo preenchido nos dois com valores diferentes NÃO é sobrescrito: vai para ``_divergencias``
     (cada cadastro foi coletado numa data; a conferência é de quem usa a tela).
  4. Campos que só existem no completo vão para ``_extras``, já agrupados e com rótulo legível.
  5. CGM que só existe no completo vira um aluno com os rótulos do básico preenchidos a partir dele.

Metadados acrescentados a cada aluno (todos começam com ``_`` e não entram na lista de campos do cadastro):
``_cadastro`` ("completo" | "basico" | "so_completo"), ``_coleta_completo``, ``_extras``,
``_preenchido_completo`` e ``_divergencias``.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Optional

# ── chave do completo → rótulo do cadastro básico (campos que existem nos dois) ─────────────────────
EQUIVALENTES: dict[str, str] = {
    "nome": "Nome",
    "cgm": "CGM",
    "data_nascimento": "Data Nascimento",
    "sexo": "Sexo",
    "estado_civil": "Estado Civil",
    "municipio_nascimento": "Município Nascimento",
    "uf_naturalidade": "UF Nascimento",
    "tipo_nacionalidade": "Nacionalidade",
    "raca_cor": "Cor",
    "rg": "RG",
    "data_expedicao_rg": "Data Expedição RG",
    "orgao_emissor_rg": "Órgão Emissor",
    "uf_rg": "UF RG",
    "cpf": "CPF",
    "nome_mae": "Mãe",
    "nome_pai": "Pai",
    "nome_responsavel": "Responsável",
    "parentesco_responsavel": "Parentesco",
    "cpf_responsavel": "CPF Responsável",
    "cep": "CEP",
    "uf": "UF",
    "cidade": "Cidade",
    "endereco": "Endereço",
    "numero_endereco": "Número",
    "complemento_endereco": "Complemento",
    "bairro": "Bairro",
    "cel_aluno": "Celular Aluno",
    "cel_responsavel": "Celular Responsável",
    "fone_residencial": "Telefone Residencial",
    "fone_comercial": "Telefone Comercial",
    "email_aluno": "Email Aluno",
    "email_responsavel": "Email Responsável",
    "bolsa_familia": "Bolsa Família",
    "nis_estudante": "NIS Estudante",
    "nis_responsavel": "NIS Responsável",
}

# ── campos que só o completo traz: (grupo, chave, rótulo), na ordem de exibição ─────────────────────
EXTRAS: list[tuple[str, str, str]] = [
    ("Identificação (completo)", "cod_inep", "Código INEP"),
    ("Identificação (completo)", "modalidade", "Modalidade"),
    ("Identificação (completo)", "ultima_serie_cursada_texto", "Última série cursada"),
    ("Identificação (completo)", "pais_origem", "País de origem"),
    ("Identificação (completo)", "povo_indigena", "Povo indígena"),
    ("Documentação", "modelo_certidao", "Modelo da certidão"),
    ("Documentação", "tipo_certidao", "Tipo da certidão"),
    ("Documentação", "data_emissao_certidao", "Emissão da certidão"),
    ("Documentação", "uf_cartorio", "UF do cartório"),
    ("Documentação", "municipio_cartorio", "Município do cartório"),
    ("Documentação", "nome_cartorio", "Cartório"),
    ("Documentação", "nome_cartorio_antigo", "Cartório (nome antigo)"),
    ("Documentação", "numero_certidao", "Nº da certidão"),
    ("Documentação", "folha_certidao", "Folha"),
    ("Documentação", "livro_certidao", "Livro"),
    ("Documentação", "matricula_certidao", "Matrícula da certidão"),
    ("Documentação", "titulo_eleitor", "Título de eleitor"),
    ("Documentação", "zona_eleitoral", "Zona eleitoral"),
    ("Documentação", "secao_eleitoral", "Seção eleitoral"),
    ("Documentação", "possui_passaporte", "Possui passaporte"),
    ("Documentação", "passaporte_rne_rnm", "Passaporte / RNE / RNM"),
    ("Família (completo)", "rg_mae", "RG da mãe"),
    ("Família (completo)", "uf_rg_mae", "UF do RG da mãe"),
    ("Família (completo)", "cel_mae", "Celular da mãe"),
    ("Família (completo)", "rg_pai", "RG do pai"),
    ("Família (completo)", "uf_rg_pai", "UF do RG do pai"),
    ("Família (completo)", "cpf_pai", "CPF do pai"),
    ("Família (completo)", "cel_pai", "Celular do pai"),
    ("Família (completo)", "filiacao3", "Filiação 3"),
    ("Contato (completo)", "ramal", "Ramal"),
    ("Endereço (completo)", "pais_residencia", "País de residência"),
    ("Endereço (completo)", "zona_residencial", "Zona residencial"),
    ("Endereço (completo)", "tipo_ident_geo", "Tipo de identificação geográfica"),
    ("Endereço (completo)", "num_ident_geo", "Nº de identificação geográfica"),
    ("Endereço (completo)", "localizacao_diferenciada", "Localização diferenciada"),
    ("Programas sociais", "cad_unico", "CadÚnico"),
    ("Perfil socioeconômico", "renda_familiar", "Renda familiar"),
    ("Perfil socioeconômico", "tipo_moradia", "Tipo de moradia"),
    ("Perfil socioeconômico", "forma_ocupacao_moradia", "Forma de ocupação"),
    ("Perfil socioeconômico", "tipo_construcao", "Tipo de construção"),
    ("Perfil socioeconômico", "tipo_conexao_internet", "Conexão de internet"),
    ("Perfil socioeconômico", "servicos_moradia", "Serviços na moradia"),
    ("Perfil socioeconômico", "itens_moradia", "Itens na moradia"),
    ("Perfil socioeconômico", "com_quem_reside", "Com quem reside"),
    ("Perfil socioeconômico", "qtd_pessoas_residem", "Pessoas na residência"),
    ("Necessidades especiais", "deficiencias", "Deficiências"),
    ("Necessidades especiais", "recursos_prova", "Recursos para prova"),
    ("Necessidades especiais", "atend_educacional", "Atendimento educacional especializado"),
    ("Observação", "observacao", "Observação"),
]

_VAZIOS = {"", "—", "-", "none", "null"}


def _texto(valor: Any) -> str:
    """Valor de qualquer tipo → texto de exibição ('' se vazio). Listas e deficiências viram uma frase."""
    if valor is None:
        return ""
    if isinstance(valor, dict):
        nome = str(valor.get("nome") or "").strip()
        detalhes = []
        if str(valor.get("requer_atendimento") or "").strip():
            detalhes.append(f"requer atendimento: {str(valor['requer_atendimento']).strip()}")
        if str(valor.get("diagnostico") or "").strip():
            detalhes.append(f"diagnóstico: {str(valor['diagnostico']).strip()}")
        if nome:
            return f"{nome} ({'; '.join(detalhes)})" if detalhes else nome
        return "; ".join(f"{k}: {v}" for k, v in valor.items() if str(v or "").strip())
    if isinstance(valor, (list, tuple, set)):
        return "; ".join(t for t in (_texto(v) for v in valor) if t)
    texto = str(valor).replace("\xa0", " ").strip()
    return "" if texto.lower() in _VAZIOS else texto


def _chave(texto: str) -> str:
    """Forma comparável: sem acento, sem maiúsculas, só letras e dígitos (telefone/CEP/CPF com ou sem pontuação)."""
    sem = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return "".join(c for c in sem.lower() if c.isalnum())


def _iguais(a: str, b: str) -> bool:
    """Igualdade tolerante: ignora acento/pontuação e aceita um valor ser abreviação do outro (M × Masculino)."""
    ka, kb = _chave(a), _chave(b)
    if ka == kb:
        return True
    return bool(ka and kb and (ka.startswith(kb) or kb.startswith(ka)))


def indexar_completo(bruto: Any) -> dict[str, dict]:
    """alunos_completo.json → {cgm: registro}. Aceita o formato atual (dict por CGM) e uma lista de dicts."""
    if isinstance(bruto, dict):
        itens = bruto.items()
    elif isinstance(bruto, list):
        itens = ((str(r.get("cgm", "")), r) for r in bruto if isinstance(r, dict))
    else:
        return {}
    saida: dict[str, dict] = {}
    for cgm, reg in itens:
        if not isinstance(reg, dict):
            continue
        cgm = str(reg.get("cgm") or cgm).strip()
        if cgm:
            saida[cgm] = reg
    return saida


def _cgm_do_basico(aluno: dict) -> str:
    return str(aluno.get("CGM", aluno.get("cgm", ""))).strip()


def _extras_do_completo(reg: dict) -> list[dict]:
    extras = []
    for grupo, chave, rotulo in EXTRAS:
        valor = _texto(reg.get(chave))
        if valor:
            extras.append({"grupo": grupo, "rotulo": rotulo, "valor": valor})
    return extras


def unificar(aluno: dict, completo: Optional[dict]) -> dict:
    """
    Acrescenta ao cadastro básico (``aluno``, alterado no lugar e devolvido) o que o cadastro completo sabe.
    Sem registro completo, só marca ``_cadastro = "basico"``.
    """
    if not completo:
        aluno["_cadastro"] = "basico"
        return aluno

    preenchidos: list[str] = []
    divergencias: list[dict] = []
    for chave, rotulo in EQUIVALENTES.items():
        valor_completo = _texto(completo.get(chave))
        if not valor_completo:
            continue
        valor_basico = _texto(aluno.get(rotulo))
        if not valor_basico:
            aluno[rotulo] = valor_completo
            preenchidos.append(rotulo)
        elif not _iguais(valor_basico, valor_completo):
            divergencias.append({"rotulo": rotulo, "basico": valor_basico, "completo": valor_completo})

    aluno["_cadastro"] = "completo"
    aluno["_coleta_completo"] = str(completo.get("timestamp_coleta") or "").strip()
    aluno["_extras"] = _extras_do_completo(completo)
    aluno["_preenchido_completo"] = preenchidos
    aluno["_divergencias"] = divergencias
    return aluno


def aluno_so_completo(cgm: str, completo: dict) -> dict:
    """Aluno que só tem cadastro completo (o básico ainda não foi coletado): monta os rótulos do básico a partir dele."""
    aluno: dict = {}
    for chave, rotulo in EQUIVALENTES.items():
        valor = _texto(completo.get(chave))
        if valor:
            aluno[rotulo] = valor
    aluno.setdefault("CGM", str(cgm).strip())                       # a chave do arquivo vale se o campo veio vazio
    if "Nome" not in aluno and _texto(completo.get("nome_turmas_json")):
        aluno["Nome"] = _texto(completo.get("nome_turmas_json"))    # nome como está em turmas.json
    unificar(aluno, completo)
    aluno["_cadastro"] = "so_completo"
    aluno["_preenchido_completo"] = []     # nada foi "completado": o básico não existe
    return aluno
