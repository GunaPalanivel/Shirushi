"""Paired company outcomes, exact tests and conservative simultaneous intervals."""
import math


def mcnemar(gains, losses):
    if type(gains) is not int or type(losses) is not int or min(gains, losses) < 0:
        raise ValueError('Nonnegative paired discordance counts required')
    total = gains + losses
    return min(1.0, 2 * sum(math.comb(total, k) for k in range(min(gains, losses) + 1)) / (1 << total))


def binomial_cdf(k, n, p):
    if p == 0:
        return 1.0
    if p == 1:
        return float(k >= n)
    return min(1.0, math.fsum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1)
        - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)) for i in range(k + 1)))


def clopper_pearson(count, total, alpha):
    def solve(k, target):
        low, high = 0.0, 1.0
        for _ in range(70):
            mid = (low + high) / 2
            if binomial_cdf(k, total, mid) > target:
                low = mid
            else:
                high = mid
        return (low + high) / 2
    lower = 0.0 if count == 0 else solve(count - 1, 1 - alpha / 2)
    upper = 1.0 if count == total else solve(count, alpha / 2)
    return lower, upper


def paired(control, challenger, family_count=2):
    if (not control or set(control) != set(challenger)
            or any(type(v) is not bool for v in list(control.values()) + list(challenger.values()))
            or type(family_count) is not int or family_count < 1):
        raise ValueError('Same nonempty labelled identities and boolean outcomes required')
    gains = sum(not control[s] and challenger[s] for s in control)
    losses = sum(control[s] and not challenger[s] for s in control)
    total = len(control)
    # Union bound over gain/loss marginals and predeclared content families.
    # Valid conservative simultaneous 95% interval, without a bootstrap claim.
    g = clopper_pearson(gains, total, 0.05 / (2 * family_count))
    l = clopper_pearson(losses, total, 0.05 / (2 * family_count))
    return {'labelled_positive_companies': total, 'control_covered': sum(control.values()),
            'challenger_covered': sum(challenger.values()), 'additional_covered_companies': gains,
            'lost_covered_companies': losses, 'net_additional_companies': gains - losses,
            'gain_percentage_points': 100 * (gains - losses) / total,
            'exact_two_sided_mcnemar_p': mcnemar(gains, losses),
            'simultaneous_95_percent_gain_interval_pp': [100 * (g[0] - l[1]), 100 * (g[1] - l[0])],
            'interval_method': 'Bonferroni exact-binomial marginals; conservative paired difference',
            'official_score': None}


def holm(pvalues):
    ordered = sorted(pvalues, key=pvalues.get)
    result, floor = {}, 0.0
    for index, name in enumerate(ordered):
        floor = max(floor, min(1.0, (len(ordered) - index) * pvalues[name]))
        result[name] = floor
    return result
