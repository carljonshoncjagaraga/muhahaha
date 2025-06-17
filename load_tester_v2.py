# -*- coding: utf-8 -*-
# load_tester_v2.py: Ferramenta de Teste de Carga com Monitor em Tempo Real
import asyncio
import aiohttp
import time
import argparse
import statistics
import numpy as np
from faker import Faker
from colorama import init, Fore, Style
from collections import Counter

# --- NOVO: Importa a biblioteca tqdm para usar o método 'write' ---
from tqdm import tqdm

# Inicializa o colorama para terminais Windows
init()

class LoadTester:
    def __init__(self, args):
        self.base_url = args.url.rstrip('/')
        self.endpoint = args.endpoint
        self.api_url = f"{self.base_url}{self.endpoint}"
        self.total_requests = args.total
        self.start_index = args.start
        self.concurrency = args.concurrency
        self.timeout = args.timeout
        # --- NOVO: Parâmetros para o monitor ---
        self.monitor_endpoint = args.monitor_endpoint
        self.monitor_url = f"{self.base_url}{self.monitor_endpoint}"
        self.check_interval = args.intervalo_check
        
        self.fake = Faker('pt_BR')
        self.status_counter = Counter()
        self.latencies = []
        self.running = True

    def _print_header(self, message):
        print(f"\n{Fore.YELLOW}{Style.BRIGHT}{'='*60}\n{message.center(60)}\n{'='*60}{Style.RESET_ALL}")

    def _print_info(self, key, value):
        print(f"{Fore.CYAN}{key:<25}{Style.RESET_ALL}{value}")

    def _print_success(self, key, value):
        print(f"{Fore.GREEN}{key:<25}{Style.RESET_ALL}{value}")
    
    def _print_failure(self, key, value):
        print(f"{Fore.RED}{key:<25}{Style.RESET_ALL}{value}")

    def get_user_payload(self, user_id):
        return {
            "nome": self.fake.name(), "email": f"user_{user_id}_{self.fake.user_name()}@test.com",
            "senha": "SenhaForteParaTeste@123!",
            "data_nascimento": self.fake.date_of_birth(minimum_age=18, maximum_age=70).strftime('%Y-%m-%d')
        }

    async def make_request(self, session, user_id, semaphore, pbar):
        async with semaphore:
            start_req_time = time.monotonic()
            try:
                payload = self.get_user_payload(user_id)
                async with session.post(self.api_url, json=payload) as response:
                    status = response.status
                    self.status_counter[status] += 1
            except asyncio.TimeoutError:
                self.status_counter['Timeout'] += 1
            except aiohttp.ClientError:
                self.status_counter['Client_Error'] += 1
            finally:
                end_req_time = time.monotonic()
                latency_ms = (end_req_time - start_req_time) * 1000
                self.latencies.append(latency_ms)
                pbar.update(1)

    # --- NOVO: Função do Monitor em tempo real ---
    async def monitor_total_users(self, session):
        """Verifica periodicamente o total de usuários cadastrados."""
        while self.running:
            try:
                await asyncio.sleep(self.check_interval)
                if not self.running: break # Checagem extra para sair do loop imediatamente
                
                async with session.get(self.monitor_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        total_users = len(data)
                        # Usa tqdm.write para não quebrar a barra de progresso
                        tqdm.write(f"{Fore.MAGENTA}[MONITOR] Total de usuários cadastrados: {total_users}{Style.RESET_ALL}")
                    else:
                        tqdm.write(f"{Fore.RED}[MONITOR] Erro ao buscar total de usuários. Status: {response.status}{Style.RESET_ALL}")
            except Exception as e:
                tqdm.write(f"{Fore.RED}[MONITOR] Falha na requisição do monitor: {e}{Style.RESET_ALL}")

    def print_final_report(self, duration):
        self._print_header("Relatório Final do Teste de Carga")
        rate = self.total_requests / duration if duration > 0 else 0
        self._print_info("Tempo Total de Execução:", f"{duration:.2f} segundos")
        self._print_info("Taxa de Requisições:", f"{rate:.2f} reqs/segundo")
        print()
        if self.latencies:
            self._print_info("Latência Mínima (ms):", f"{min(self.latencies):.2f}")
            self._print_info("Latência Média (ms):", f"{statistics.mean(self.latencies):.2f}")
            self._print_info("Latência P90 (ms):", f"{np.percentile(self.latencies, 90):.2f}")
            self._print_info("Latência P95 (ms):", f"{np.percentile(self.latencies, 95):.2f}")
            self._print_info("Latência P99 (ms):", f"{np.percentile(self.latencies, 99):.2f}")
            self._print_info("Latência Máxima (ms):", f"{max(self.latencies):.2f}")
        print()
        self._print_info("Total de Requisições:", self.total_requests)
        for status, count in sorted(self.status_counter.items()):
            if status == 201:
                self._print_success(f"  - Sucesso ({status}):", f"{count} ocorrências")
            else:
                self._print_failure(f"  - Falha ({status}):", f"{count} ocorrências")

    async def run(self):
        self._print_header("Iniciando Teste de Carga com Monitor")
        self._print_info("URL de Carga:", self.api_url)
        self._print_info("URL do Monitor:", self.monitor_url)
        self._print_info("Total de Requisições:", self.total_requests)
        self._print_info("Nível de Concorrência:", self.concurrency)
        self._print_info("Intervalo do Monitor:", f"{self.check_interval} segundos")
        
        start_time = time.monotonic()
        semaphore = asyncio.Semaphore(self.concurrency)
        timeout_config = aiohttp.ClientTimeout(total=self.timeout)

        async with aiohttp.ClientSession(timeout=timeout_config) as session:
            # --- NOVO: Inicia a tarefa do monitor em segundo plano ---
            monitor_task = asyncio.create_task(self.monitor_total_users(session))
            
            with tqdm(total=self.total_requests, unit=" req") as pbar:
                tasks = [
                    self.make_request(session, i, semaphore, pbar)
                    for i in range(self.start_index, self.start_index + self.total_requests)
                ]
                await asyncio.gather(*tasks)

            # --- NOVO: Para e aguarda o monitor finalizar ---
            self.running = False
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass # Erro esperado ao cancelar

        duration = time.monotonic() - start_time
        self.print_final_report(duration)

def main():
    parser = argparse.ArgumentParser(description="Ferramenta de Teste de Carga com Monitor de Usuários em Tempo Real.")
    # Argumentos do Teste de Carga
    parser.add_argument('--total', type=int, required=True, help="Número total de requisições de carga a serem enviadas.")
    parser.add_argument('--concurrency', type=int, default=50, help="Número de requisições de carga simultâneas.")
    parser.add_argument('--endpoint', type=str, default="/api/usuarios/cadastrar", help="Endpoint da API para o teste de carga (ex: /cadastrar).")
    # Argumentos do Monitor
    parser.add_argument('--monitor-endpoint', type=str, default="/api/usuarios", help="Endpoint da API para buscar a lista de usuários.")
    parser.add_argument('--intervalo-check', type=int, default=10, help="Intervalo em segundos para o monitor verificar o total de usuários.")
    # Argumentos Gerais
    parser.add_argument('--url', type=str, default="http://20.106.203.90:5000", help="URL base do servidor.")
    parser.add_argument('--start', type=int, default=0, help="Índice inicial para os dados gerados.")
    parser.add_argument('--timeout', type=int, default=30, help="Timeout em segundos para cada requisição.")
    
    args = parser.parse_args()
    
    tester = LoadTester(args)
    asyncio.run(tester.run())

if __name__ == "__main__":
    main()