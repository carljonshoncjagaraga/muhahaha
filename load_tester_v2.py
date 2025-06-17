# -*- coding: utf-8 -*-
# render_stress_tester.py: Ferramenta de Teste de Estresse para Cloud (Render)
import asyncio
import aiohttp
import time
import argparse
import statistics
import numpy as np
from faker import Faker
from colorama import init, Fore, Style
from collections import Counter

# Inicializa o colorama para terminais Windows (e funciona em logs do Render)
init(autoreset=True)

class StressTester:
    """
    Classe principal que orquestra o teste de estresse, projetada para eficiência
    de memória e controle de longa duração em plataformas de nuvem.
    """
    def __init__(self, args):
        # Configurações do Teste
        self.base_url = args.url.rstrip('/')
        self.endpoint = args.endpoint
        self.api_url = f"{self.base_url}{self.endpoint}"
        self.concurrency = args.concurrency
        self.timeout = args.timeout
        self.runtime_minutes = args.runtime

        # Configurações do Monitor
        self.monitor_endpoint = args.monitor_endpoint
        self.monitor_url = f"{self.base_url}{self.monitor_endpoint}"
        self.check_interval = args.intervalo_check
        
        # Estado e Coleta de Dados
        self.fake = Faker('pt_BR')
        self.status_counter = Counter()
        self.latencies = []
        self.running = True
        self.start_time = time.monotonic()
        self.requests_sent = 0

    def _print_header(self, message):
        print(f"\n{Fore.YELLOW}{Style.BRIGHT}{'='*60}\n{message.center(60)}\n{'='*60}")

    def _print_info(self, key, value):
        print(f"{Fore.CYAN}{key:<25}{Style.RESET_ALL}{value}")

    def _print_success(self, key, value):
        print(f"{Fore.GREEN}{key:<25}{Style.RESET_ALL}{value}")
    
    def _print_failure(self, key, value):
        print(f"{Fore.RED}{key:<25}{Style.RESET_ALL}{value}")

    def get_user_payload(self, user_id):
        """Gera a carga de dados (payload) para a requisição."""
        return {
            "nome": self.fake.name(),
            "email": f"user_{user_id}_{int(time.time())}_{self.fake.user_name()}@test.com",
            "senha": "SenhaForteParaTeste@123!",
            "data_nascimento": self.fake.date_of_birth(minimum_age=18, maximum_age=70).strftime('%Y-%m-%d')
        }

    async def make_request(self, session, user_id):
        """Executa uma única requisição, mede latência e trata erros."""
        start_req_time = time.monotonic()
        try:
            payload = self.get_user_payload(user_id)
            async with session.post(self.api_url, json=payload) as response:
                self.status_counter[response.status] += 1
        except asyncio.TimeoutError:
            self.status_counter['Timeout'] += 1
        except aiohttp.ClientError:
            self.status_counter['Client_Error'] += 1
        finally:
            latency_ms = (time.monotonic() - start_req_time) * 1000
            self.latencies.append(latency_ms)
            self.requests_sent += 1

    async def worker(self, session):
        """
        Um 'trabalhador' que envia requisições continuamente. Esta arquitetura
        usa memória constante, crucial para evitar 'Out of Memory'.
        """
        user_id_counter = 0
        while self.running:
            await self.make_request(session, user_id_counter)
            user_id_counter += 1

    async def monitor_total_users(self, session):
        """Verifica periodicamente o total de usuários cadastrados."""
        while self.running:
            try:
                await asyncio.sleep(self.check_interval)
                if not self.running: break
                
                async with session.get(self.monitor_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        print(f"{Fore.MAGENTA}[MONITOR] Total de usuários na base: {len(data)}")
                    else:
                        print(f"{Fore.RED}[MONITOR] Erro ao buscar total de usuários. Status: {response.status}")
            except Exception:
                if self.running: print(f"{Fore.RED}[MONITOR] Falha na requisição do monitor.")

    async def print_periodic_stats(self):
        """Imprime estatísticas de performance a cada 10 segundos."""
        while self.running:
            await asyncio.sleep(10)
            if not self.running: break
            
            duration = time.monotonic() - self.start_time
            rate = self.requests_sent / duration if duration > 0 else 0
            print(f"{Fore.WHITE}[STATS] Rodando por {duration:.0f}s. Requisições enviadas: {self.requests_sent}. Taxa: {rate:.2f} reqs/s")
            
    def print_final_report(self, duration):
        """Imprime o relatório final detalhado do teste."""
        self._print_header("Relatório Final do Teste de Estresse")
        rate = self.requests_sent / duration if duration > 0 else 0
        self._print_info("Duração Total do Teste:", f"{duration:.2f} segundos")
        self._print_info("Taxa Média de Requisições:", f"{rate:.2f} reqs/segundo")
        if self.latencies:
            self._print_info("Latência Média (ms):", f"{statistics.mean(self.latencies):.2f}")
            self._print_info("Latência P95 (ms):", f"{np.percentile(self.latencies, 95):.2f}")
            self._print_info("Latência Máxima (ms):", f"{max(self.latencies):.2f}")
        print()
        self._print_info("Total de Requisições:", self.requests_sent)
        for status, count in sorted(self.status_counter.items()):
            if status == 201:
                self._print_success(f"  - Sucesso ({status}):", f"{count} ocorrências")
            else:
                self._print_failure(f"  - Falha ({status}):", f"{count} ocorrências")

    async def run(self):
        """Orquestra a execução do teste, lidando com o tempo de execução e a finalização."""
        self._print_header("Iniciando Teste de Estresse para Cloud")
        if self.runtime_minutes > 0:
            self._print_info("Duração do Teste:", f"{self.runtime_minutes} minutos")
        else:
            self._print_info("Duração do Teste:", "Contínua (até parada manual)")
        self._print_info("Para parar localmente:", "Pressione Ctrl+C")

        tasks = []
        timeout_config = aiohttp.ClientTimeout(total=self.timeout)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout_config) as session:
                tasks.append(asyncio.create_task(self.monitor_total_users(session)))
                tasks.append(asyncio.create_task(self.print_periodic_stats()))
                for _ in range(self.concurrency):
                    tasks.append(asyncio.create_task(self.worker(session)))
                
                test_duration_seconds = self.runtime_minutes * 60 if self.runtime_minutes > 0 else None
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=test_duration_seconds)

        except (KeyboardInterrupt, asyncio.TimeoutError) as e:
            if isinstance(e, asyncio.TimeoutError):
                print(f"\n{Fore.YELLOW}Tempo de execução de {self.runtime_minutes} minutos atingido. Finalizando...")
            else: # KeyboardInterrupt
                print(f"\n{Fore.YELLOW}Sinal de interrupção recebido. Finalizando...")
        finally:
            self.running = False
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            duration = time.monotonic() - self.start_time
            self.print_final_report(duration)

def main():
    parser = argparse.ArgumentParser(description="Ferramenta de Teste de Estresse para Cloud.")
    parser.add_argument('--url', type=str, default="http://20.106.203.90:5000", help="URL base do servidor.")
    parser.add_argument('--endpoint', type=str, default="/api/usuarios/cadastrar", help="Endpoint de carga.")
    parser.add_argument('--monitor-endpoint', type=str, default="/api/usuarios", help="Endpoint do monitor.")
    parser.add_argument('--concurrency', type=int, default=50, help="Requisições simultâneas.")
    parser.add_argument('--runtime', type=int, default=0, help="Tempo de execução em minutos (0 para infinito).")
    parser.add_argument('--timeout', type=int, default=30, help="Timeout da requisição em segundos.")
    parser.add_argument('--intervalo-check', type=int, default=15, help="Intervalo em segundos do monitor.")
    
    args = parser.parse_args()
    tester = StressTester(args)
    asyncio.run(tester.run())

if __name__ == "__main__":
    main()
