"""Run explicitly: python -m app.telemetry_maintenance --delete-expired"""
import argparse
from .database import make_engine, session_factory
from .telemetry import delete_expired


def main():
    parser = argparse.ArgumentParser(description='Delete expired telemetry and its event/receipt/checkpoint rows')
    parser.add_argument('--delete-expired', action='store_true', required=True)
    parser.parse_args()
    with session_factory(make_engine())() as db:
        print(f'Deleted {delete_expired(db)} expired telemetry sessions (including their dependent records).')


if __name__ == '__main__': main()
