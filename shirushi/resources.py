"""Worker allowance inside the official launcher's inherited process limits."""
import os


def worker_memory_limit():
    value = os.environ.get('SHIRUSHI_WORKER_ADDRESS_SPACE_LIMIT')
    if value is not None:
        import resource
        cap = int(value)
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        if cap <= 0 or cap > 8_000_000_000 or (hard != resource.RLIM_INFINITY and cap > hard):
            raise ValueError('Worker memory allowance exceeds inherited hard limit')
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
