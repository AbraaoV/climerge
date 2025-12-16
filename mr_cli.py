#!/usr/bin/env python3
"""
CLI para criar Merge Requests em múltiplas branches e comentar no JIRA
Suporta GitLab e GitHub
"""

import os
import sys
import argparse
import requests
from pathlib import Path
from typing import Optional, Dict, List


def load_env_file():
    """Carrega variáveis do arquivo .env"""
    # Procura o arquivo .env em várias localizações
    env_paths = [
        Path.home() / '.mr-jira' / '.env',  # ~/.mr-jira/.env
        Path.home() / '.env',  # ~/.env
        Path.cwd() / '.env',  # ./.env (diretório atual)
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
        
        # Monta o conteúdo com links clicáveis
        content = []
        for mr in merge_requests:
            if mr['target'] == 'release-candidate':
                label = 'RELEASE CANDIDATE: '
            elif mr['target'] == 'test-release':
                label = 'TEST RELEASE: '
            else:
                label = ''
            
            # Adiciona parágrafo com texto e link
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
                         jira_key: Optional[str] = None) -> List[Dict]:
    """Cria MRs para test-release e release-candidate"""
    
    results = []
    target_branches = ['test-release', 'release-candidate']
    
    # Verifica se deve desabilitar SSL
    verify_ssl = os.getenv('VERIFY_SSL', 'true').lower() != 'false'
    
    if platform == 'gitlab':
        gitlab_url = os.getenv('GITLAB_URL', 'https://gitlab.com')
        gitlab_token = os.getenv('GITLAB_TOKEN')
        project_id = os.getenv('GITLAB_PROJECT_ID')
        
        if not gitlab_token or not project_id:
            raise ValueError("GITLAB_TOKEN e GITLAB_PROJECT_ID são obrigatórios")
        
        client = GitLabClient(gitlab_url, gitlab_token, verify_ssl)
        
        for target in target_branches:
            # Define o prefixo do título baseado na branch alvo
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
            # Define o prefixo do título baseado na branch alvo
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
    
    # Verifica se deve desabilitar SSL
    verify_ssl = os.getenv('VERIFY_SSL', 'true').lower() != 'false'
    
    client = JiraClient(jira_url, jira_email, jira_token, verify_ssl)
    
    print(f"\nComentando no JIRA {jira_key}...")
    client.add_comment(jira_key, merge_requests)
    print(f"✓ Comentário adicionado ao {jira_key}")
    
    # Registra horas se fornecido
    if time_spent:
        print(f"\nRegistrando {time_spent} de trabalho no {jira_key}...")
        client.log_work(jira_key, time_spent, "Tempo gasto na criação dos merge requests")
        print(f"✓ {time_spent} registrado no {jira_key}")


def setup_config():
    """Cria o arquivo de configuração interativamente"""
    config_dir = Path.home() / '.mr-jira'
    config_file = config_dir / '.env'
    
    print("=== Configuração do MR-JIRA CLI ===\n")
    
    # Cria o diretório se não existir
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
        description='Cria Merge Requests e comenta no JIRA',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:

  # Primeiro, configure:
  mr-jira --setup
  
  # Criar MRs sem registrar horas:
  mr-jira gitlab feature/nova-funcionalidade "Implementa nova feature" --jira PROJ-123
  
  # Criar MRs e registrar 2 horas:
  mr-jira gitlab feature/nova-funcionalidade "Implementa nova feature" --jira PROJ-123 --time-spent 2h
  
  # Criar MRs e registrar 1 hora e 30 minutos:
  mr-jira gitlab feature/nova-funcionalidade "Implementa nova feature" --jira PROJ-123 -t "1h 30m"
  
  # Formatos aceitos para tempo: 1h, 30m, 2h 30m, 1d, 1d 4h, 1w 2d 4h 30m
        """
    )
    
    parser.add_argument('--setup', action='store_true',
                       help='Configurar o CLI interativamente')
    parser.add_argument('platform', nargs='?', choices=['gitlab', 'github'], 
                       help='Plataforma Git (gitlab ou github)')
    parser.add_argument('source_branch', nargs='?', help='Branch de origem')
    parser.add_argument('title', nargs='?', help='Título do MR/PR')
    parser.add_argument('--jira', '-j', dest='jira_key', 
                       help='Chave do chamado JIRA (ex: PROJ-123)')
    parser.add_argument('--time-spent', '-t', dest='time_spent',
                       help='Tempo gasto para registrar no JIRA (ex: 1h, 30m, 2h 30m, 1d 4h)')
    parser.add_argument('--no-jira-comment', action='store_true',
                       help='Não comentar no JIRA')
    
    args = parser.parse_args()
    
    # Modo de configuração
    if args.setup:
        setup_config()
        return
    
    # Validação de argumentos
    if not all([args.platform, args.source_branch, args.title]):
        parser.print_help()
        sys.exit(1)
    
    # Carrega o arquivo .env
    if not load_env_file():
        print("⚠ Nenhum arquivo .env encontrado!")
        print("Execute 'mr-jira --setup' para configurar")
        sys.exit(1)
    
    try:
        # Cria os MRs/PRs
        merge_requests = create_merge_requests(
            platform=args.platform,
            source_branch=args.source_branch,
            title=args.title,
            jira_key=args.jira_key
        )
        
        # Comenta no JIRA se solicitado
        if args.jira_key and not args.no_jira_comment:
            comment_on_jira(args.jira_key, merge_requests, args.time_spent)
        
        print("\n✓ Processo concluído com sucesso!")
        
    except requests.HTTPError as e:
        print(f"✗ Erro HTTP: {e.response.status_code} - {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"✗ Erro de configuração: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Erro: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()