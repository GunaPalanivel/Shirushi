"""Empirical route selection; unknown sources receive bounded exploration."""
ROUTE_FAMILIES = {'brreg_roles': {'people'}, 'brreg_accounts': {'financials_history'},
                  'brreg_subunits': {'operating_locations'},
                  'company_owned': {'business_products', 'website_owned_profiles', 'jobs_dated_activity'}}


class Planner:
    def __init__(self, policy='fixed'):
        self.policy, self.statistics = policy, {}

    def choose(self, pending, covered):
        if self.policy == 'fixed':
            return pending[0]
        def priority(route):
            stats = self.statistics.get(route)
            novelty = len(ROUTE_FAMILIES[route] - covered)
            if stats is None:
                return (1, novelty, 0)  # Explore each available route before relying on estimates.
            expected = (stats['gains'] + 1) / (stats['attempts'] + 2)
            cost = max(1, stats['requests'] / stats['attempts'])
            return (0, novelty * expected / cost, expected / cost)
        return max(pending, key=priority)

    def observe(self, route, new_families, unique_facts, requests):
        stats = self.statistics.setdefault(route, {'attempts': 0, 'gains': 0, 'unique_facts': 0, 'requests': 0})
        stats['attempts'] += 1
        stats['gains'] += len(new_families)
        stats['unique_facts'] += unique_facts
        stats['requests'] += requests
