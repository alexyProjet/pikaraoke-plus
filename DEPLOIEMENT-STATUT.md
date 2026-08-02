# Statut du déploiement PiKaraoke-Plus — TERMINÉ

Dernière mise à jour : 2 août 2026 (soir)

## Déploiement terminé — tout est en place

1. **Code** : PR #1 (features), PR #2 (outillage deploy), PR #3 (fix permissions /mnt/media), PR #4 (pont dans la racine Samba) — toutes fusionnées dans `master`.
2. **Pi** : service systemd `pikaraoke` **actif**, installé via Contrôle-Pi (projet `karaoke`, clone dans `/home/alexy/karaoke`) + `deploy/install-pi.sh` (idempotent : relancer = mettre à jour).
   - http://192.168.1.157:5555 → HTTP 200 (splash : `/splash`)
   - Chansons : `/mnt/media/karaoke` — pont PC : `/mnt/media/data/karaoke-analyse` (= `DATA_ROOT` de Notflex, exposé par le Samba du conteneur)
   - Mot de passe admin : `Karaoke-2026` (stocké dans `/home/alexy/.pikaraoke/pikaraoke.env`, jamais dans le repo)
   - `enable_fair_queue` pré-activé dans `~/.pikaraoke/config.ini`
3. **PC** : Nightingale 1.0.0 installé (`%LOCALAPPDATA%\Nightingale\Nightingale.exe`), lecteur `K:` → `\\192.168.1.157\data` (persistant, `alexy`/`Projo-2026`), pont visible en `K:\karaoke-analyse` (testé de bout en bout).
4. **SSH rétabli** : clé `memories-pc2` réinstallée dans `authorized_keys` via Contrôle-Pi (projet temporaire, retiré ensuite). ⚠ Utiliser le ssh **PowerShell** (agent Windows) — le ssh de Git Bash ne joint pas l'agent.
5. **Guide** : `C:\Users\Alexy\Desktop\guide-karaoke.html`.

## Reste à faire (action manuelle d'Alexy)

- Premier lancement de Nightingale : pointer la bibliothèque sur `K:\karaoke-analyse` (assistant graphique).
- Optionnel : PRs upstream ciblées vers vicwomg/pikaraoke ; relecture des 84 traductions fr machine.

## Mises à jour futures

Contrôle-Pi → carte **Karaoke** → « Mettre à jour » (git pull + `bash deploy/install-pi.sh`).
