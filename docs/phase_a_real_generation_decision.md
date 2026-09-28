# Phase A — Décision sur l'activation de la génération réelle

- **Date :** 2026-09-27
- **Référence :** `main` à `5ae61489f3cbc0e15f315eb781d56c11a17e696e` (CI verte : tests + `NO_DRIFT`)
- **Statut :** décision en vigueur

## Décision

**NO-GO pour toute activation réelle pour le moment. Provider = CLOSED.**

Ce document consigne une décision de **non-activation**. Il n'autorise aucune génération réelle et ne constitue pas un engagement à ouvrir le Provider à une date ou à une condition donnée. Remplir les conditions ci-dessous rend seulement possible une **nouvelle décision distincte**, qui pourra elle-même être négative.

Le travail futur peut porter sur le durcissement des contrôles. Aucun des quatre verrous d'exécution ne doit être ouvert dans cette phase, ni dans les phases de durcissement qui suivent :

1. `ControlledRealProviderActivationService._fresh_violations()` refuse tout contrat contre le Provider réel (`agents/controlled_real_provider_activation.py`, identité de méthode `HiggsfieldProvider.create_job`).
2. `HiggsfieldProvider.create_job()` se termine par un `raise HiggsfieldRealGenerationDisabledError` inconditionnel (`integrations/higgsfield/provider.py`).
3. `HiggsfieldClient.create_job()` est un `raise` unique, verrouillé par un test AST (P3.83, `integrations/higgsfield/client.py`).
4. `HiggsfieldClient.run()` n'exécute que les verbes en lecture seule (`_READ_ONLY_CLI_VERBS`) : `generate create` est refusé avant tout processus.

## Conditions préalables à toute nouvelle décision d'ouverture

Les sept conditions suivantes doivent toutes être remplies **avant** qu'une décision d'ouverture puisse seulement être envisagée. Au moment de cette décision future, leur respect devra être démontré par des preuves (tests, audit) : il s'agit du moyen de le constater, pas d'une condition supplémentaire.

1. **Identité authentifiée de l'autorisateur.** L'autorisation actuelle (`RealGenerationAuthorization`) est un objet construit en mémoire par n'importe quel code du processus, avec un champ `note` en texte libre. Ce n'est pas suffisant : l'identité de la personne qui autorise doit être authentifiée.
2. **Autorisation explicite, liée, courte et à usage unique.** L'autorisation doit être liée à une requête précise (`request_id`) et à ses hashes (prompt, avatar, référence visage). Elle expire au plus tard 300 secondes après son émission et ne peut servir qu'une seule fois.
3. **Plafond de crédits par requête.** Un plafond numérique doit être fixé par décision explicite du propriétaire du projet avant toute ouverture. **Aucun montant n'est fixé par ce document.**
4. **Coût `UNKNOWN` toujours bloquant.** Un coût inconnu doit bloquer l'exécution dans tous les cas, y compris lorsque l'approbation et l'autorisation humaine sont toutes deux présentes.
5. **Révocation persistante et journal d'audit durable.** La révocation d'une autorisation ou d'un contrat doit survivre à la fin du processus. Un journal durable et append-only doit tracer les autorisations, préparations, refus et tentatives, sans jamais contenir de secret ni de token.
6. **Périmètre limité à Video 005.** Seule la Release Candidate Video 005, avec ses hashes verrouillés (`agents/release_candidate_identity_lock.py`, `VIDEO_005_RELEASE_CANDIDATE`), est éligible, sauf décision ultérieure explicite.
7. **Arrêt et refermeture immédiats.** Une procédure documentée et testée doit permettre d'arrêter et de refermer immédiatement. Les verrous actuels restent en place tant qu'une nouvelle autorisation distincte n'a pas été donnée.

## Contrôles déjà présents

| Domaine | Mécanisme existant | Emplacement |
|---|---|---|
| Double consentement | `approved` (technique/budget) et `RealGenerationAuthorization` (humain) sont indépendants, jamais déduits l'un de l'autre | `agents/generation_approval_gate.py` (`RealGenerationAuthorization`, `_human_authorization_reasons`) |
| Liaison à la requête | L'autorisation doit porter le `request_id` exact et `authorized_by_human is True` | `agents/generation_approval_gate.py` (`_human_authorization_reasons`) |
| Contrats d'activation | Deux contrats (P2.21, P2.26) en mémoire, à usage unique, liés à l'instance émettrice, expirant après 300 s | `agents/activation_contract.py`, `agents/controlled_real_provider_activation.py` |
| Vérification à la frontière | Le Provider recompare les valeurs live (request_id, type de job, paramètres, SHA du prompt, de l'avatar et de la référence visage, fraîcheur) | `integrations/higgsfield/provider.py` (`_provider_activation_violations`) |
| Coût et budget | Coût KNOWN / UNKNOWN / ERROR ; ERROR -> BLOCKED ; solde lu via le Provider ; solde insuffisant -> BLOCKED | `agents/generation_cost_service.py`, `agents/generation_approval_gate.py` |
| Identité du contenu | Identity Lock sur Video 005 (prompt et assets recalculés depuis le disque) | `agents/release_candidate_identity_lock.py` |
| Idempotence et anti-rejeu | Registre persistant à écriture atomique, marqueur « en vol » durable avant `create_job()`, état `EXECUTION_STATE_UNKNOWN` bloquant, `job_id` persisté | `agents/executed_request_store.py`, `agents/generation_job_service.py` |
| Concurrence | Verrou de section critique inter-processus autour de la séquence complète | `agents/critical_section_lock.py` |
| Fermeture par défaut | Les quatre verrous ci-dessus ; un contrat fourni sans son service lève une `ValueError` ; `run_video_mission()` ne fournit jamais de contrat | `agents/generation_job_service.py`, `director.py` |
| Séparation Mock / réel | Tests de génération sur `MockHiggsfieldProvider` ; tests du client hermétiques ; Provider réel détecté par identité de méthode | `integrations/higgsfield/mock_provider.py`, tests P3.83 / P3.85 / P3.86-C |
| Contrôle continu | Cardinalités `execute` = 1 et `create_job` de production = 1, détecteur de dérive `NO_DRIFT`, CI GitHub Actions sur les push et pull requests ciblant `main`, et manuellement via `workflow_dispatch` | `agents/architecture_drift_detector.py`, `.github/workflows/ci.yml` |

## Lacunes à combler

| Condition | Écart constaté |
|---|---|
| 1. Identité authentifiée | Aucun système d'identité : l'autorisation est constructible en mémoire, `note` est un texte libre |
| 2. Autorisation expirante | `authorized_at` est défini mais jamais vérifié : l'autorisation elle-même n'expire pas (seuls les contrats expirent après 300 s) |
| 3. Plafond de crédits | Aucun plafond par requête ni par période : la seule limite serait le solde du compte |
| 4. `UNKNOWN` toujours bloquant | Aujourd'hui, un coût `UNKNOWN` peut être `APPROVED` si l'approbation et l'autorisation humaine sont toutes deux présentes |
| 5. Révocation et audit | `revoke()` existe seulement en mémoire, sur le contrat Provider ; aucune révocation du contrat de requête ; aucune révocation persistante ; aucun journal durable des autorisations, préparations, refus et tentatives |
| 6. Périmètre Video 005 | Déjà respecté par l'Identity Lock ; à maintenir |
| 7. Arrêt et refermeture | Aucune procédure documentée ni testée de refermeture après une éventuelle ouverture |

## Ce que ce document n'autorise pas

- Aucune génération réelle, aucun appel à `create_job()`, aucune consommation de crédits.
- Aucune modification visant à ouvrir les quatre verrous d'exécution ou à affaiblir les tests qui les verrouillent (P3.83, preflight, cardinalités). La maintenance de ces tests reste possible tant qu'elle n'assouplit aucune protection.
- Aucune promesse d'ouverture future, quel que soit l'avancement du durcissement.

## Révision de cette décision

Seule une nouvelle décision écrite, distincte de celle-ci, peut modifier ce statut. Elle doit constater, preuves à l'appui, que les sept conditions ci-dessus sont remplies, et fixer explicitement le plafond de crédits. Tant qu'elle n'existe pas : **Provider = CLOSED, génération réelle = 0, crédits = 0.**
