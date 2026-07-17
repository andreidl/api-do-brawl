# Instala a tarefa agendada 'ApiDoBrawl_Rastreio' no Windows:
# consulta os jogadores do banco a cada 2h e acumula batalhas novas.
# Rodar UMA vez (PowerShell): .\instalar_rastreio.ps1
# Desinstalar: Unregister-ScheduledTask -TaskName "ApiDoBrawl_Rastreio" -Confirm:$false

$projeto = "C:\projetos\api-do-brawl"
$acao = New-ScheduledTaskAction -Execute "$projeto\.venv\Scripts\python.exe" `
    -Argument "-m app.rastrear" -WorkingDirectory $projeto
$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(10) `
    -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration ([TimeSpan]::MaxValue)
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "ApiDoBrawl_Rastreio" -Action $acao `
    -Trigger $gatilho -Settings $config `
    -Description "API do Brawl - rastreia batalhas dos jogadores do banco a cada 2h (log em data\rastreio.log)"

Write-Host "Tarefa 'ApiDoBrawl_Rastreio' instalada. Log: $projeto\data\rastreio.log"
