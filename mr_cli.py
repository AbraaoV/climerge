#!/usr/bin/env python3
"""
CLI para criar Merge Requests em múltiplas branches e comentar no JIRA
Suporta GitLab e GitHub
"""

import os
import sys
import argparse
import requests
import subprocess
import re
from pathlib import Path
from typing import Optional, Dict, List


def load_env_file():
    """Carrega variáveis do arquivo .env"""
    env_paths = [
        Path.home() / '.mr-jira' / '.env',  
        Path.home() / '.env',  
        Path.cwd() / '.env',  
                ]
    
    for env_path in env_paths:
        if env_path.exists():
            print(f"Carregando configurações de: {env_path}")
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            # Remove aspas se existirem
                            value = value.strip().strip('"').strip("'")
                            os.environ[key.strip()] = value
            return True
    return False


def run_command(command: List[str]) -> str:
    """Executa um comando no shell e retorna o stdout, ou lança exceção em caso de erro."""
    try:
        # print(f"Executando: {' '.join(command)}")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,  # Lança exceção em caso de erro
            encoding='utf-8'
        )
        return result.stdout.strip()
    except FileNotFoundError:
        print(f"✗ Erro: O comando '{command[0]}' não foi encontrado. O Git está instalado e no PATH?", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"✗ Erro ao executar comando: {' '.join(command)}", file=sys.stderr)
        print(f"  Stderr: {e.stderr.strip()}", file=sys.stderr)
        raise


def get_current_branch() -> str:
    """Retorna o nome da branch git atual."""
    return run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])


def has_upstream_branch() -> bool:
    """Verifica se a branch atual possui uma upstream branch configurada."""
    try:
        run_command(['git', 'rev-parse', '@{u}'])
        return True
    except subprocess.CalledProcessError:
        return False


def push_current_branch(branch_name: str):
    """Executa 'git push --set-upstream' para a branch atual."""
    run_command(['git', 'push', '--set-upstream', 'origin', branch_name])
    print(f"✓ Branch '{branch_name}' enviada para o repositório remoto.")


class GitLabClient:
    def __init__(self, url: str, token: str, verify_ssl: bool = True):
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {'PRIVATE-TOKEN': token}
        self.verify_ssl = verify_ssl
    
    def create_merge_request(self, project_id: str, source_branch: str, 
                            target_branch: str, title: str, description: str = "") -> Dict:
        endpoint = f"{self.url}/api/v4/projects/{project_id}/merge_requests"
        data = {
            'source_branch': source_branch,
            'target_branch': target_branch,
            'title': title,
            'description': description
        }
        response = requests.post(endpoint, headers=self.headers, json=data, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()


class GitHubClient:
    def __init__(self, token: str, verify_ssl: bool = True):
        self.token = token
        self.headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        self.verify_ssl = verify_ssl
    
    def create_pull_request(self, owner: str, repo: str, head: str, 
                           base: str, title: str, body: str = "") -> Dict:
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        data = {
            'head': head,
            'base': base,
            'title': title,
            'body': body
        }
        response = requests.post(endpoint, headers=self.headers, json=data, verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()


class JiraClient:
    def __init__(self, url: str, email: str, token: str, verify_ssl: bool = True):
        self.url = url.rstrip('/')
        self.auth = (email, token)
        self.verify_ssl = verify_ssl
    
    def log_work(self, issue_key: str, time_spent: str, comment: str = "") -> Dict:
        """Registra horas trabalhadas no chamado"""
        endpoint = f"{self.url}/rest/api/3/issue/{issue_key}/worklog"
        data = {
            'timeSpent': time_spent,
        }
        if comment:
            data['comment'] = {
                'type': 'doc',
                'version': 1,
                'content': [
                    {
                        'type': 'paragraph',
                        'content': [
                            {
                                'type': 'text',
                                'text': comment
                            }
                        ]
                    }
                ]
            }
        response = requests.post(endpoint, auth=self.auth, json=data,
                                headers={'Content-Type': 'application/json'},
                                verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()
    
    def add_comment(self, issue_key: str, merge_requests: List[Dict]) -> Dict:
        endpoint = f"{self.url}/rest/api/3/issue/{issue_key}/comment"
        
        content = []
        for mr in merge_requests:
            if mr['target'] == 'release-candidate':
                label = 'RELEASE CANDIDATE: '
            elif mr['target'] == 'test-release':
                label = 'TEST RELEASE: '
            else:
                label = ''
            
            content.append({
                'type': 'paragraph',
                'content': [
                    {
                        'type': 'text',
                        'text': label
                    },
                    {
                        'type': 'text',
                        'text': mr['url'],
                        'marks': [
                            {
                                'type': 'link',
                                'attrs': {
                                    'href': mr['url']
                                }
                            }
                        ]
                    }
                ]
            })
        
        data = {
            'body': {
                'type': 'doc',
                'version': 1,
                'content': content
            }
        }
        response = requests.post(endpoint, auth=self.auth, json=data, 
                                headers={'Content-Type': 'application/json'}, 
                                verify=self.verify_ssl)
        response.raise_for_status()
        return response.json()


def create_merge_requests(platform: str, source_branch: str, title: str, 
                         jira_key: Optional[str] = None,
                         target_branches: List[str] = None) -> List[Dict]:
    """Cria MRs para as branches de destino informadas (padrão: test-release e release-candidate)"""
    
    if target_branches is None:
        target_branches = ['test-release', 'release-candidate']
    
    results = []
    
    verify_ssl = os.getenv('VERIFY_SSL', 'true').lower() != 'false'
    
    if platform == 'gitlab':
        gitlab_url = os.getenv('GITLAB_URL', 'https://gitlab.com')
        gitlab_token = os.getenv('GITLAB_TOKEN')
        project_id = os.getenv('GITLAB_PROJECT_ID')
        
        if not gitlab_token or not project_id:
            raise ValueError("GITLAB_TOKEN e GITLAB_PROJECT_ID são obrigatórios")
        
        client = GitLabClient(gitlab_url, gitlab_token, verify_ssl)
        
        for target in target_branches:
            if target == 'test-release':
                mr_title = f"[TEST RELEASE] {title}"
            elif target == 'release-candidate':
                mr_title = f"[RELEASE CANDIDATE] {title}"
            else:
                mr_title = title
            
            print(f"Criando MR: {source_branch} -> {target}")
            mr = client.create_merge_request(
                project_id=project_id,
                source_branch=source_branch,
                target_branch=target,
                title=mr_title,
                description=f"JIRA: {jira_key}" if jira_key else ""
            )
            results.append({
                'target': target,
                'url': mr['web_url'],
                'iid': mr['iid']
            })
            print(f"✓ MR #{mr['iid']} criado: {mr['web_url']}")
    
    elif platform == 'github':
        github_token = os.getenv('GITHUB_TOKEN')
        repo_owner = os.getenv('GITHUB_OWNER')
        repo_name = os.getenv('GITHUB_REPO')
        
        if not all([github_token, repo_owner, repo_name]):
            raise ValueError("GITHUB_TOKEN, GITHUB_OWNER e GITHUB_REPO são obrigatórios")
        
        client = GitHubClient(github_token, verify_ssl)
        
        for target in target_branches:
            if target == 'test-release':
                pr_title = f"[TEST RELEASE] {title}"
            elif target == 'release-candidate':
                pr_title = f"[RELEASE CANDIDATE] {title}"
            else:
                pr_title = title
            
            print(f"Criando PR: {source_branch} -> {target}")
            pr = client.create_pull_request(
                owner=repo_owner,
                repo=repo_name,
                head=source_branch,
                base=target,
                title=pr_title,
                body=f"JIRA: {jira_key}" if jira_key else ""
            )
            results.append({
                'target': target,
                'url': pr['html_url'],
                'number': pr['number']
            })
            print(f"✓ PR #{pr['number']} criado: {pr['html_url']}")
    
    return results


def comment_on_jira(jira_key: str, merge_requests: List[Dict], time_spent: Optional[str] = None):
    """Adiciona comentário no JIRA com os links dos MRs e opcionalmente registra horas"""
    
    jira_url = os.getenv('JIRA_URL')
    jira_email = os.getenv('JIRA_EMAIL')
    jira_token = os.getenv('JIRA_TOKEN')
    
    if not all([jira_url, jira_email, jira_token]):
        raise ValueError("JIRA_URL, JIRA_EMAIL e JIRA_TOKEN são obrigatórios")
    
    verify_ssl = os.getenv('VERIFY_SSL', 'true').lower() != 'false'
    
    client = JiraClient(jira_url, jira_email, jira_token, verify_ssl)
    
    print(f"\nComentando no JIRA {jira_key}...")
    client.add_comment(jira_key, merge_requests)
    print(f"✓ Comentário adicionado ao {jira_key}")
    
    if time_spent:
        print(f"\nRegistrando {time_spent} de trabalho no {jira_key}...")
        client.log_work(jira_key, time_spent, "Tempo gasto na criação dos merge requests")
        print(f"✓ {time_spent} registrado no {jira_key}")


def handle_push_command(args: argparse.Namespace):
    """Lida com a lógica do comando 'push'."""
    
    # 1. Obter branch atual e verificar se estamos em um repositório git
    try:
        source_branch = get_current_branch()
        print(f"Branch atual: {source_branch}")
    except subprocess.CalledProcessError:
        print("✗ Erro: Não parece ser um repositório git ou nenhum commit foi feito.", file=sys.stderr)
        sys.exit(1)

    # 2. Verificar se a branch já foi enviada; se não, fazer push
    if not has_upstream_branch():
        print(f"A branch '{source_branch}' ainda não possui uma upstream. Enviando para 'origin'...")
        push_current_branch(source_branch)
    else:
        status = run_command(['git', 'status', '-sb'])
        if '[ahead' in status:
            print("Existem commits locais que não estão no remoto. Executando 'git push'...")
            run_command(['git', 'push'])
        else:
            print(f"✓ A branch '{source_branch}' já está sincronizada com o repositório remoto.")

    # 3. Determinar chave do JIRA
    jira_key = args.jira_key
    if not jira_key:
        match = re.search(r'([a-zA-Z]+-\d+)', source_branch)
        if match:
            jira_key = match.group(1).upper()
            print(f"✓ Chave do JIRA encontrada na branch: {jira_key}")
        else:
            raise ValueError("Chave do JIRA não informada com '--jira' e não encontrada no nome da branch.")

    # 4. Determinar título do MR/PR
    title = args.title if args.title else source_branch.replace('_', ' ').replace('-', ' ')
    print(f"Título do MR/PR: {title}")

    # 5. Determinar plataforma
    platform = None
    if os.getenv('GITLAB_URL') and os.getenv('GITLAB_TOKEN'):
        platform = 'gitlab'
    elif os.getenv('GITHUB_TOKEN') and os.getenv('GITHUB_OWNER'):
        platform = 'github'
    else:
        raise ValueError("Não foi possível determinar a plataforma Git. Verifique as variáveis GITLAB_* ou GITHUB_* no seu .env")
    
    print(f"Plataforma Git detectada: {platform}")

    # 6. Criar Merge/Pull Requests
    merge_requests = create_merge_requests(
        platform=platform,
        source_branch=source_branch,
        title=title,
        jira_key=jira_key,
        target_branches=getattr(args, 'target_branches', None)
    )

    # 7. Comentar no JIRA e registrar horas (se aplicável)
    if not args.no_jira_comment:
        comment_on_jira(jira_key, merge_requests, args.time_spent)

    print("\n✓ Comando 'push' concluído com sucesso!")


def setup_config():
    """Cria o arquivo de configuração interativamente"""
    config_dir = Path.home() / '.mr-jira'
    config_file = config_dir / '.env'
    
    print("=== Configuração do MR-JIRA CLI ===\n")
    
    config_dir.mkdir(exist_ok=True)
    
    print("Escolha a plataforma Git:")
    print("1. GitLab")
    print("2. GitHub")
    platform = input("Escolha (1 ou 2): ").strip()
    
    config_lines = []
    
    if platform == "1":
        print("\n--- Configuração GitLab ---")
        gitlab_url = input("URL do GitLab [https://gitlab.com]: ").strip() or "https://gitlab.com"
        gitlab_token = input("GitLab Token: ").strip()
        gitlab_project_id = input("GitLab Project ID: ").strip()
        
        config_lines.extend([
            f"GITLAB_URL={gitlab_url}",
            f"GITLAB_TOKEN={gitlab_token}",
            f"GITLAB_PROJECT_ID={gitlab_project_id}"
        ])
    else:
        print("\n--- Configuração GitHub ---")
        github_token = input("GitHub Token: ").strip()
        github_owner = input("GitHub Owner (usuário/organização): ").strip()
        github_repo = input("GitHub Repo (nome do repositório): ").strip()
        
        config_lines.extend([
            f"GITHUB_TOKEN={github_token}",
            f"GITHUB_OWNER={github_owner}",
            f"GITHUB_REPO={github_repo}"
        ])
    
    print("\n--- Configuração JIRA ---")
    jira_url = input("JIRA URL (ex: https://empresa.atlassian.net): ").strip()
    jira_email = input("JIRA Email: ").strip()
    jira_token = input("JIRA API Token: ").strip()
    
    config_lines.extend([
        f"JIRA_URL={jira_url}",
        f"JIRA_EMAIL={jira_email}",
        f"JIRA_TOKEN={jira_token}"
    ])
    
    # Salva o arquivo
    with open(config_file, 'w') as f:
        f.write("# Configuração MR-JIRA CLI\n")
        f.write("# Gerado automaticamente\n\n")
        f.write("\n".join(config_lines))
    
    print(f"\n✓ Configuração salva em: {config_file}")
    print("\nAgora você pode usar o comando de qualquer lugar!")


def main():
    parser = argparse.ArgumentParser(
        description='CLI para automação de Git e JIRA.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:

  # Primeiro, configure o CLI (será salvo em ~/.mr-jira/.env):
  mr_cli.py --setup
  
  # Comando PUSH (novo):
  # Detecta a branch atual, faz o push se necessário, cria os MRs e comenta no JIRA.
  # A chave do JIRA é extraída do nome da branch (ex: TXPOA-1234-minha-feature).
  # O título do MR é gerado a partir do nome da branch.
  mr_cli.py push
  
  # Registrando 2h de trabalho no JIRA:
  mr_cli.py push -t 2h
  
  # Fornecendo um título customizado para o MR:
  mr_cli.py push --title "Refatoração do Módulo de Pagamentos"
  
  # Comando CREATE (antigo):
  # Para criar MRs manualmente para uma branch específica.
  mr_cli.py create gitlab feature/nova-func "Implementa nova feature" --jira PROJ-123
  
  # Formatos de tempo: 1h, 30m, 2h 30m, 1d, 1w 2d 4h 30m
        """
    )
    
    parser.add_argument('--setup', action='store_true',
                       help='Configurar o CLI interativamente')

    subparsers = parser.add_subparsers(dest='command', help='Comandos disponíveis')
    subparsers.required = False # Allow `mr-cli --setup` without a command

    # --- Comando 'create' (funcionalidade original) ---
    parser_create = subparsers.add_parser('create', help='Cria MRs/PRs manualmente para branches específicas')
    parser_create.add_argument('platform', choices=['gitlab', 'github'], 
                       help='Plataforma Git (gitlab ou github)')
    parser_create.add_argument('source_branch', help='Branch de origem')
    parser_create.add_argument('title', help='Título do MR/PR')
    parser_create.add_argument('--jira', '-j', dest='jira_key', 
                       help='Chave do chamado JIRA (ex: PROJ-123)')
    parser_create.add_argument('--time-spent', '-t', dest='time_spent',
                       help='Tempo gasto para registrar no JIRA (ex: 1h, 30m)')
    parser_create.add_argument('--no-jira-comment', action='store_true',
                       help='Não comentar no JIRA')
    parser_create.add_argument('--test-release', '-tr', action='store_true',
                       help='Abrir MR apenas para test-release')
    parser_create.add_argument('--release-candidate', '-rc', action='store_true',
                       help='Abrir MR apenas para release-candidate')

    # --- Comando 'push' (nova funcionalidade) ---
    parser_push = subparsers.add_parser('push', help='Automatiza o push, criação de MR/PR e comentário no JIRA para a branch atual')
    parser_push.add_argument('--time-spent', '-t', dest='time_spent',
                       help='Tempo gasto para registrar no JIRA (ex: 1h, 30m)')
    parser_push.add_argument('--jira', '-j', dest='jira_key',
                       help='Forçar uma chave do JIRA específica (ignora a da branch)')
    parser_push.add_argument('--title',
                       help='Forçar um título específico para o MR/PR (ignora o da branch)')
    parser_push.add_argument('--no-jira-comment', action='store_true',
                       help='Não comentar no JIRA, apenas criar os MRs/PRs')
    parser_push.add_argument('--test-release', '-tr', action='store_true',
                       help='Abrir MR apenas para test-release')
    parser_push.add_argument('--release-candidate', '-rc', action='store_true',
                       help='Abrir MR apenas para release-candidate')

    args = parser.parse_args()
    
    if args.setup:
        setup_config()
        return
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if not load_env_file():
        print("⚠ Nenhum arquivo .env encontrado!")
        print("Execute 'mr_cli.py --setup' para configurar.")
        sys.exit(1)
    
    # Determinar branches de destino baseadas nas flags
    target_branches = []
    if args.test_release:
        target_branches.append('test-release')
    if args.release_candidate:
        target_branches.append('release-candidate')
    
    # Se nenhuma flag for informada, usa o padrão (ambas)
    if not target_branches:
        target_branches = ['test-release', 'release-candidate']

    try:
        if args.command == 'create':
            # Validação de argumentos para 'create'
            if not all([args.platform, args.source_branch, args.title]):
                parser_create.print_help()
                sys.exit(1)
            
            merge_requests = create_merge_requests(
                platform=args.platform,
                source_branch=args.source_branch,
                title=args.title,
                jira_key=args.jira_key,
                target_branches=target_branches
            )
            
            if args.jira_key and not args.no_jira_comment:
                comment_on_jira(args.jira_key, merge_requests, args.time_spent)
            
            print("\n✓ Processo 'create' concluído com sucesso!")

        elif args.command == 'push':
            # Passamos target_branches para o handler do push
            args.target_branches = target_branches
            handle_push_command(args)

    except requests.HTTPError as e:
        print(f"✗ Erro HTTP: {e.response.status_code} - {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"✗ Erro de configuração ou validação: {e}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError:
        # A mensagem de erro já foi impressa pela função run_command
        sys.exit(1)
    except Exception as e:
        print(f"✗ Erro inesperado: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()