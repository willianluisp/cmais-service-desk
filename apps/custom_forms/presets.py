"""Versioned C+ draft templates; importing this module never writes to the database."""
from uuid import UUID, uuid5

FIELD_NAMESPACE = UUID("904ea00b-a7f7-5679-9731-d18ca0168385")


def _field(key, name, kind, label, required=True, options=(), help_text=""):
    return {
        "id": str(uuid5(FIELD_NAMESPACE, f"cmais:{key}:{name}")),
        "type": kind, "label": label, "required": required,
        "help_text": help_text, "placeholder": "", "options": list(options),
        "default": [] if kind == "multiple" else "",
    }


def get_cmais_presets():
    """Return fresh data on each call, with field identity independent of labels/order."""
    def form(key, title, description, icon, fields, *, sensitive=False):
        return {
            "provision_key": key, "title": title, "description": description,
            "icon": icon, "fields": [_field(key, *field) for field in fields],
            "is_sensitive": sensitive,
        }

    return [
        form("support", "Suporte de TI",
            "Solicite suporte para problemas técnicos com computadores, notebooks, monitores e periféricos.",
            "support", [
                ("equipment", "short_text", "Equipamento afetado"),
                ("problem", "select", "Tipo de problema", True, [
                    "Computador lento ou travando", "Computador não liga", "Monitor ou tela",
                    "Teclado ou mouse", "Internet ou rede", "Erro no Windows", "Outro"]),
                ("description", "long_text", "Descrição do problema"),
                ("started", "date", "Quando começou?", False),
                ("attachment", "attachment", "Imagem ou captura do erro", False),
            ]),
        form("access", "Acessos e Permissões",
            "Solicite criação, alteração ou liberação de acessos aos sistemas e recursos corporativos.",
            "access", [
                ("resource", "select", "Sistema ou recurso", True, [
                    "Questor", "SharePoint", "OneDrive", "Outlook", "Pastas corporativas", "VPN", "Outro"]),
                ("request", "select", "Tipo de solicitação", True, [
                    "Novo acesso", "Alteração de permissão", "Problema com acesso", "Revogação de acesso"]),
                ("employee", "short_text", "Colaborador que precisa do acesso"),
                ("reason", "long_text", "Justificativa"),
                ("date", "date", "Prazo desejado", False),
            ]),
        form("printers", "Impressoras e Scanners",
            "Solicite suporte para impressão, digitalização, instalação e problemas com impressoras.",
            "equipment", [
                ("printer", "short_text", "Impressora ou equipamento"),
                ("problem", "select", "Tipo de problema", True, [
                    "Não imprime", "Impressão com falhas", "Não digitaliza", "Impressora desconectada", "Instalação", "Outro"]),
                ("description", "long_text", "Descrição"),
                ("attachment", "attachment", "Foto ou captura do erro", False),
            ]),
        form("microsoft365", "E-mail e Microsoft 365",
            "Solicite suporte para Outlook, Teams, OneDrive, SharePoint e serviços Microsoft 365.",
            "access", [
                ("service", "select", "Serviço afetado", True, [
                    "Outlook", "Teams", "OneDrive", "SharePoint", "Conta Microsoft", "Outro"]),
                ("problem", "select", "Tipo de problema", True, [
                    "Não consigo acessar", "Problema de sincronização", "Erro no envio ou recebimento", "Configuração", "Outro"]),
                ("description", "long_text", "Descrição"),
                ("attachment", "attachment", "Captura do erro", False),
            ]),
        form("equipment", "Solicitação de Equipamentos",
            "Solicite equipamentos e periféricos necessários às atividades profissionais.",
            "equipment", [
                ("equipment", "select", "Equipamento solicitado", True, [
                    "Computador", "Notebook", "Monitor", "Teclado", "Mouse", "Headset", "Outro"]),
                ("quantity", "integer", "Quantidade", True, (),
                    "Informe uma quantidade inteira positiva. A solicitação não aprova automaticamente a compra."),
                ("reason", "long_text", "Justificativa"),
                ("date", "date", "Data desejada", False),
                ("employee", "short_text", "Colaborador que utilizará o equipamento"),
            ]),
        form("software", "Instalação de Programas",
            "Solicite instalação, atualização ou configuração de programas utilizados na empresa.",
            "request", [
                ("program", "short_text", "Nome do programa"),
                ("request", "select", "Tipo de solicitação", True, [
                    "Instalação", "Atualização", "Reinstalação", "Configuração", "Remoção"]),
                ("equipment", "short_text", "Equipamento de destino"),
                ("reason", "long_text", "Justificativa", True, (),
                    "A execução depende das licenças e autorizações necessárias."),
                ("date", "date", "Data desejada", False),
            ]),
        form("offboarding", "Desligamento de Colaborador",
            "Solicite à equipe responsável os procedimentos de TI relacionados ao desligamento de um colaborador.",
            "people", [
                ("employee", "short_text", "Nome completo do colaborador"),
                ("sector", "sector", "Setor do colaborador desligado"),
                ("date", "date", "Data prevista do desligamento"),
                ("block_at", "datetime", "Horário previsto para bloqueio dos acessos"),
                ("type", "select", "Tipo de desligamento", True, [
                    "Desligamento programado", "Desligamento imediato", "Outro"]),
                ("systems", "multiple", "Sistemas e acessos a revisar", True, [
                    "Conta Windows/AD", "Microsoft 365", "Outlook", "SharePoint/OneDrive", "VPN", "Questor", "Outros"]),
                ("equipment", "multiple", "Equipamentos a recolher", False, [
                    "Computador", "Notebook", "Monitor", "Celular", "Periféricos", "Outros"]),
                ("notes", "long_text", "Observações para a equipe de TI", False, (),
                    "Informe apenas o necessário para os procedimentos de TI, sem motivos pessoais desnecessários."),
            ], sensitive=True),
    ]
