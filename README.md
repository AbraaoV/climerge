# MR-JIRA CLI

CLI para criar Merge Requests (MRs) em múltiplas branches no GitLab ou Pull Requests (PRs) no GitHub, e opcionalmente comentar no JIRA com os links dos MRs/PRs criados, além de registrar horas trabalhadas.

Suporta plataformas GitLab e GitHub, com integração ao JIRA para comentários e log de trabalho.

## Funcionalidades

- Cria MRs/PRs automaticamente para branches `test-release` e `release-candidate` (ou apenas uma delas se especificado).
- Adiciona comentários no JIRA com links dos MRs/PRs criados.
- Registra horas trabalhadas no JIRA (opcional).
- Configuração interativa via comando `--setup`.
- Suporte a variáveis de ambiente via arquivo `.env`.

## Requisitos

- Python 3.6+
- Biblioteca `requests` (instale com `pip install requests`)

## Instalação

1. Clone ou baixe o repositório.
2. Instale o pacote globalmente usando o `pip`:
   ```bash
   pip install .
   ```
   *Nota: Se estiver em um ambiente de desenvolvimento, você pode usar `pip install -e .` para que as alterações no código sejam refletidas imediatamente.*

Após a instalação, o comando `mr-cli` estará disponível globalmente no seu terminal.

## Configuração

Execute o comando de configuração interativa:

```bash
mr-cli --setup
```

Ou crie manualmente um arquivo `.env` em um dos caminhos suportados:
- `~/.mr-jira/.env`
- `~/.env`
- `./.env` (no diretório atual)

### Variáveis de Ambiente

#### Para GitLab:
- `GITLAB_URL`: URL do GitLab (padrão: https://gitlab.com)
- `GITLAB_TOKEN`: Token de acesso pessoal do GitLab
- `GITLAB_PROJECT_ID`: ID do projeto no GitLab

#### Para GitHub:
- `GITHUB_TOKEN`: Token de acesso pessoal do GitHub
- `GITHUB_OWNER`: Proprietário do repositório (usuário ou organização)
- `GITHUB_REPO`: Nome do repositório

#### Para JIRA:
- `JIRA_URL`: URL do JIRA (ex: https://empresa.atlassian.net)
- `JIRA_EMAIL`: Email da conta JIRA
- `JIRA_TOKEN`: Token de API do JIRA


## Uso

### Comando `push` (Recomendado)

Automatiza todo o fluxo: detecta a branch atual, faz o push para o remoto (se necessário), extrai a chave do JIRA do nome da branch, cria os MRs/PRs e comenta no JIRA.

```bash
mr-cli push [-t <time>] [-j <jira_key>] [--title <title>] [--no-jira-comment] [-tr] [-rc]
```

- `-t` ou `--time-spent`: Registra horas no JIRA.
- `-j` ou `--jira`: Informa a chave do JIRA manualmente (se não estiver no nome da branch).
- `--title`: Título customizado para o MR/PR.
- `--no-jira-comment`: Não comenta no JIRA.
- `-tr` ou `--test-release`: Cria MR/PR apenas para `test-release`.
- `-rc` ou `--release-candidate`: Cria MR/PR apenas para `release-candidate`.

#### Exemplos com `push`

```bash
# Fluxo completo (cria MRs para test-release e release-candidate)
mr-cli push

# Apenas para test-release com registro de 1h
mr-cli push -tr -t 1h

# Apenas para release-candidate
mr-cli push -rc
```

### Comando `create` (Manual)

Cria MRs/PRs manualmente para uma branch específica.

```bash
mr-cli create <platform> <source_branch> <title> [--jira <jira_key>] [--time-spent <time>] [--no-jira-comment] [-tr] [-rc]
```

- `<platform>`: `gitlab` ou `github`
- `<source_branch>`: Branch de origem
- `<title>`: Título do MR/PR
- Outras flags são as mesmas do comando `push`.

#### Exemplos com `create`

```bash
# Criar apenas MR de test-release no GitLab
mr-cli create gitlab feature/minha-task "Minha Task" --jira PROJ-123 -tr
```

## Formatos de Tempo Aceitos

- `30m`: 30 minutos
- `1h`: 1 hora
- `2h 30m`: 2 horas e 30 minutos
- `1d`: 1 dia
- `1d 4h`: 1 dia e 4 horas
- `1w 2d 4h 30m`: 1 semana, 2 dias, 4 horas e 30 minutos

## Tratamento de Erros

- Se variáveis obrigatórias estiverem faltando, o script exibirá uma mensagem de erro.
- Erros HTTP (ex: token inválido) serão reportados com código e mensagem.
- Certifique-se de que as branches `test-release` e `release-candidate` existam no repositório.

## Segurança

- Tokens são armazenados em arquivos `.env` (não commite no Git).
- Use HTTPS e verifique SSL (padrão: habilitado).
- Para desabilitar verificação SSL, defina `VERIFY_SSL=false` no `.env`.