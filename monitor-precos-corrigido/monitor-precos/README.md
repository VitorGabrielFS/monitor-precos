# Monitor de Preços – PS5 + GTA 6

Coleta preços de hora em hora no GitHub Actions (grátis), filtra anúncios ruins, calcula parcelas **sem juros verificadas** e avisa no Telegram.

## Publicar (≈15 min)
1. Crie conta no GitHub → **New repository** → nome `monitor-precos` → **Private** → Create.
2. Envie todos os arquivos desta pasta (inclusive a pasta oculta `.github`) pelo botão **Add file → Upload files** (arraste a pasta descompactada).
3. Em **Settings → Secrets and variables → Actions → New repository secret**, crie:
   - `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` (os seus)
   - *(recomendado)* `ML_CLIENT_ID` e `ML_CLIENT_SECRET`: app gratuito em developers.mercadolivre.com.br. Sem isso o Mercado Livre pode recusar a busca.
4. Aba **Actions** → habilite os workflows → **monitor-precos → Run workflow**. Veja o log da execução; depois ele roda sozinho.

## Usar
Telegram: `/start` `/status` `/precos` `/ajuda`. Os comandos são respondidos a cada execução (até ~1 hora de espera), pois não há servidor ligado 24h.
Ajustes (metas, orçamento, lojas, consultas): edite `config.yaml` no próprio GitHub.

## Regras do sistema
- Alerta só se preço + frete conhecido ou estimado **< meta**. Quando o frete é estimado, a mensagem avisa que o valor precisa ser confirmado. Obs.: GTA 6 Standard custa R$ 449,90 oficialmente; só haverá alerta com desconto.
- Combinação só é recomendada se **ambos** têm parcelamento **sem juros matematicamente conferido**, frete conhecido e a soma estimada das parcelas é **≤ R$ 500**. Frete estimado não gera combinação confirmada.
- Descartados: usados ou condição nova não confirmada, vendedor sem reputação verificada, preços inválidos e duplicados. Preços baixos não são descartados por piso fixo; somente valores extremos abaixo de 25% da mediana de 5 ou mais ofertas equivalentes são sinalizados como suspeitos.
- Sem notificação repetida: só reenvia se o preço cair ≥ 2%.
- Histórico em SQLite na branch `data` (sobrescrita a cada execução, repositório não cresce).

## Limitações (leia)
- **Mercado Livre** usa API oficial: é a fonte mais confiável.
- **Demais lojas** são "best effort": Amazon, KaBuM, Magalu, Casas Bahia, Ponto, Carrefour, Fast Shop, Americanas, Shopee, Pichau, TerabyteShop, Havan, Miranda, iByte e Nagem. Lemos apenas dados estruturados públicos, respeitamos `robots.txt` e **não contornamos CAPTCHA**. Muitas podem aparecer como 🚫 bloqueada, erro ou sem ofertas em `/status`; estar configurada não significa que foi acessada com sucesso. Para Pichau, TerabyteShop, Havan, Miranda, iByte e Nagem, o catálogo direto da própria loja pode ser tratado como primeira parte quando o HTML omite vendedor/condição; títulos com indicação de open-box/usado são descartados. Anúncios de marketplace continuam exigindo identificação e reputação.
- Parcelamento só é considerado se a loja informar "Nx sem juros" de forma legível; senão fica "NÃO VERIFICADO". Desconto no PIX não é capturado.
- Os coletores genéricos não têm garantia de funcionamento em todas as lojas: o HTML muda e algumas bloqueiam automação. Confira `/status` para distinguir lojas consultadas, bloqueadas e com erro.
- O GitHub pode atrasar o agendamento e pausa workflows após 60 dias sem atividade no repositório (basta reativar na aba Actions).
- Minutos grátis (repo privado): 2.000/mês. Se as execuções passarem de ~1,3 min, mantenha o cron em `.github/workflows/monitor.yml` como `"0 * * * *"` (hora em hora).

## Por que GitHub Actions
Grátis sem cartão, agenda nativa, segredos seguros. Alternativas descartadas: Oracle Cloud Free (exige cartão), Render/Railway/Fly (limites, hibernação ou cartão), PythonAnywhere free (acesso externo restrito a lista de sites, a confirmar).

## Testar no PC (opcional)
`pip install -r requirements.txt` → `python -m pytest` → `PYTHONPATH=src python -m monitor run --dry-run`
