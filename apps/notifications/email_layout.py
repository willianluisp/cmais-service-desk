"""Layout dos avisos de chamado por e-mail (cores do Portal C+), com a logo da C+ embutida (cid:).

Vai no e-mail só o que o próprio solicitante já vê no portal: protocolo, assunto, categoria,
empresa, prioridade, responsável e datas. Descrição, respostas de formulário, anexos e
observações NÃO entram (o e-mail sai da rede e pode ser encaminhado).
"""

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

ETAPAS = (("ABERTO", "Aberto"), ("EM_ATENDIMENTO", "Em andamento"), ("RESOLVIDO", "Finalizado"))

TEXTOS = {
    "ABERTO": ("Recebido", "Recebemos o seu chamado",
               "A equipe de TI vai analisar o pedido. Você recebe um novo aviso quando o atendimento começar."),
    "EM_ATENDIMENTO": ("Em andamento", "Seu chamado está em andamento",
                       "A equipe de TI começou o atendimento. Você pode acompanhar tudo pelo portal."),
    "RESOLVIDO": ("Finalizado", "Seu chamado foi finalizado",
                  "Se ainda precisar de ajuda com este assunto, abra um novo chamado pelo portal."),
}

CORES = {  # fundo e texto do selo da etapa (mesmos tons do portal)
    "ABERTO": ("#eaf3ff", "#175cd3"),
    "EM_ATENDIMENTO": ("#fff7df", "#8a5a00"),
    "RESOLVIDO": ("#e9f8f0", "#147a4b"),
}

# Logos enviadas junto como anexo embutido (cid:): aparecem sem o Outlook pedir para baixar imagens.
ASSETS = Path(__file__).resolve().parent / "assets"
MARCAS = {
    # C+ Contabilidade (a mesma logo do e-mail do Authentik): azul-marinho e verde-limão.
    "cmais": {"cid": "logo-cmais", "arquivo": ASSETS / "logo-cmais.png", "alt": "C+ Contabilidade",
              "largura": 200, "altura": 41, "acento": "#94c11f", "texto_botao": "#04162f", "titulo": "#04162f"},
    # C+ Soluções Contábeis (quem está no grupo do AD em EMAIL_SOLUCOES_GROUP_DN): azul e azul-marinho.
    "solucoes": {"cid": "logo-solucoes", "arquivo": ASSETS / "logo-solucoes.png", "alt": "C+ Soluções Contábeis",
                 "largura": 150, "altura": 41, "acento": "#007fc1", "texto_botao": "#ffffff", "titulo": "#003d58"},
}
LOGO_CID = MARCAS["cmais"]["cid"]
LOGO_ARQUIVO = MARCAS["cmais"]["arquivo"]


def _responsaveis(ticket):
    from apps.planner_integration.assignees import _display_name

    return [nome.strip() for nome in (ticket.planner_assignee_names or []) if _display_name(nome)]


def _data(valor):
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else ""


def montar(ticket, etapa, detectado_em, *, observacoes=0, marca="cmais"):
    """Devolve (assunto, texto, html) do aviso da etapa ABERTO, EM_ATENDIMENTO ou RESOLVIDO.

    Com observacoes > 0, o aviso é de observações novas da TI (o texto delas fica só no portal).
    """
    rotulo, titulo, explicacao = TEXTOS[etapa]
    cor_fundo, cor_texto = CORES[etapa]
    if observacoes:
        rotulo = "Nova observação" if observacoes == 1 else "Novas observações"
        titulo = ("Há uma nova observação no seu chamado" if observacoes == 1
                  else f"Há {observacoes} novas observações no seu chamado")
        explicacao = "A equipe de TI escreveu no seu chamado. Abra o portal para ler e acompanhar."
        cor_fundo, cor_texto = "#eaf3ff", "#175cd3"
    link = f"{settings.PORTAL_BASE_URL.rstrip('/')}/chamados/{ticket.pk}/"
    responsaveis = _responsaveis(ticket)
    campos = [
        ("Protocolo", ticket.number),
        ("Assunto", ticket.title),
        ("Categoria", ticket.category.name if ticket.category_id else ""),
        ("Empresa", ticket.company_name_snapshot),
        ("Prioridade", ticket.get_priority_display()),
        ("Responsável", ", ".join(responsaveis) if responsaveis else "Aguardando atribuição"),
        ("Aberto em", _data(ticket.created_at)),
        ("Atualização", _data(detectado_em)),
    ]
    campos = [(nome, valor) for nome, valor in campos if valor]
    indice = [codigo for codigo, _ in ETAPAS].index(etapa)
    contexto = {
        "rotulo": rotulo, "titulo": titulo, "explicacao": explicacao,
        "campos": campos, "link": link, "numero": ticket.number,
        "cor_fundo": cor_fundo, "cor_texto": cor_texto,
        "etapas": [{"nome": nome, "feita": i <= indice, "atual": i == indice} for i, (_, nome) in enumerate(ETAPAS)],
        "remetente": getattr(settings, "GRAPH_MAILBOX_ID", ""), "marca": MARCAS.get(marca, MARCAS["cmais"]),
    }
    assunto = f"[Não responder] C+ Service Desk — {ticket.number} — {rotulo}"
    linhas = [titulo + ".", explicacao, ""]
    linhas += [f"{nome}: {valor}" for nome, valor in campos]
    linhas += ["", f"Ver o chamado no portal (rede da empresa): {link}", "",
               "Aviso automático do C+ Service Desk. Esta caixa não é lida: não responda este e-mail."]
    return assunto, "\n".join(linhas), render_to_string("notifications/ticket_event.html", contexto)
