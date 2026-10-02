"""Più resolver in fila: il primo che riconosce il file vince. I resolver
dei plugin vengono prima di quelli integrati (Radarr/Sonarr, poi guessit e
TMDB): un plugin esiste di solito per un caso che quelli non coprono (es.
anime da AniDB)."""

import logging

from nazgarr.adapters.media_resolver.base import MediaResolverAdapter, ResolvedMedia

logger = logging.getLogger(__name__)


class FirstMatchResolver(MediaResolverAdapter):
    SOURCE = "chain"

    def __init__(self, resolvers: list[MediaResolverAdapter]):
        if not resolvers:
            raise ValueError("FirstMatchResolver richiede almeno un resolver")
        self.resolvers = resolvers

    def resolve(self, file_path: str) -> ResolvedMedia | None:
        errors = []
        for resolver in self.resolvers:
            try:
                resolved = resolver.resolve(file_path)
            except Exception as exc:  # uno che fallisce non ferma i successivi
                logger.warning("Resolver %s fallito su %r", type(resolver).__name__, file_path, exc_info=True)
                errors.append(exc)
                continue
            if resolved is not None:
                return resolved
        if errors and len(errors) == len(self.resolvers):
            raise errors[-1]
        return None
