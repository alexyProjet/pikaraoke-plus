# Statut du déploiement PiKaraoke-Plus

Dernière mise à jour : 5 août 2026 — regroupement des dossiers d'échange
sous `/mnt/media/data/karaoke/` (le Zidoo scannait les MP4 karaoké comme
des films depuis le partage `data` de Notflex).

## Chemins actuels (après regroupement)

- Chansons scannées : `/mnt/media/karaoke` (hors du partage, inchangé)
- Pont PC : `/mnt/media/data/karaoke/analyse` (= `K:\karaoke\analyse`)
- Atelier : `/mnt/media/data/karaoke/atelier` (= `K:\karaoke\atelier`)
- Bibliothèque convertie : `/mnt/media/data/karaoke/bibliotheque`
  (bind-mount fstab → `/mnt/media/karaoke/bibliotheque`)
- Un `.nomedia` marque `/mnt/media/data/karaoke/` : les scanners de médias
  (Zidoo, Kodi…) ignorent tout le sous-arbre.

La migration depuis l'ancienne disposition à plat (`karaoke-analyse`,
`karaoke-atelier`, `karaoke-bibliotheque` à la racine de `data`) est
automatique au prochain `deploy/install-pi.sh` : démontage de l'ancien
bind, `mv` des dossiers, remplacement de la ligne fstab.

## Déploiement en place

1. **Code** : PR #1 (features), PR #2 (outillage deploy), PR #3 (fix permissions /mnt/media), PR #4 (pont dans la racine Samba) — toutes fusionnées dans `master`.
2. **Pi** : service systemd `pikaraoke` **actif**, installé via Contrôle-Pi (projet `karaoke`, clone dans `/home/alexy/karaoke`) + `deploy/install-pi.sh` (idempotent : relancer = mettre à jour).
   - http://192.168.1.157:5555 → HTTP 200 (splash : `/splash`)
   - Mot de passe admin : `Karaoke-2026` (stocké dans `/home/alexy/.pikaraoke/pikaraoke.env`, jamais dans le repo)
   - `enable_fair_queue` pré-activé dans `~/.pikaraoke/config.ini`
3. **PC** : Nightingale 1.0.0 installé (`%LOCALAPPDATA%\Nightingale\Nightingale.exe`), lecteur `K:` → `\\192.168.1.157\data` (persistant, `alexy`/`Projo-2026`).
4. **SSH rétabli** : clé `memories-pc2` réinstallée dans `authorized_keys` via Contrôle-Pi (projet temporaire, retiré ensuite). ⚠ Utiliser le ssh **PowerShell** (agent Windows) — le ssh de Git Bash ne joint pas l'agent.
5. **Guide** : `C:\Users\Alexy\Desktop\guide-karaoke.html`.

## Reste à faire (action manuelle d'Alexy)

- Relancer `deploy/install-pi.sh` sur le Pi (Contrôle-Pi → Karaoke →
  « Mettre à jour ») pour appliquer la migration des dossiers.
- Re-exécuter `atelier\installer_pc.ps1` sur le PC (met à jour la tâche
  planifiée avec les nouveaux chemins `K:\karaoke\...`).
- Nightingale : re-pointer la bibliothèque sur `K:\karaoke\analyse`.
- Optionnel : PRs upstream ciblées vers vicwomg/pikaraoke ; relecture des 84 traductions fr machine.

## Mises à jour futures

Contrôle-Pi → carte **Karaoke** → « Mettre à jour » (git pull + `bash deploy/install-pi.sh`).
