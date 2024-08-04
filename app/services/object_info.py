import wikipedia


class ObjectInfoService:
    @staticmethod
    async def get_object_info(object_name):
        try:
            page = wikipedia.page(object_name)
            summary = wikipedia.summary(object_name, sentences=2)
            return {
                'description': summary,
                'wikiLink': page.url
            }
        except wikipedia.exceptions.DisambiguationError as e:
            return {
                'description': f"Multiple meanings found for {object_name}. Please be more specific.",
                'wikiLink': f"https://en.wikipedia.org/wiki/{object_name}_(disambiguation)"
            }
        except wikipedia.exceptions.PageError:
            return {
                'description': f"No information found for {object_name}.",
                'wikiLink': None
            }


object_info_service = ObjectInfoService()
