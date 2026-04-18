FROM postgres:16

# pg_cron schedules SQL jobs from inside Postgres.  Used by migration
# 0007 to top up rate_observations partitions every month with zero
# user intervention.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-cron \
    && rm -rf /var/lib/apt/lists/*
