"""
The command line interfact to the Twitter v2 API.
"""

import os
import re
import json
import twarc
import click
import logging
import pathlib
import configobj
import threading

from click_plugins import with_plugins
from pkg_resources import iter_entry_points
from twarc.decorators import cli_api_error
from twarc.expansions import flatten as flat
from click_config_file import configuration_option


@with_plugins(iter_entry_points('twarc.plugins'))
@click.group()
@click.option('--bearer-token', type=str, envvar='BEARER_TOKEN',
    help='Twitter app bearer token')
@click.option('--log', default='twarc.log')
@configuration_option(cmd_name='twarc')
@click.pass_context
def cli(ctx, bearer_token, log):
    """
    Collect raw data from the Twitter V2 API.
    """
    logging.basicConfig(
        filename=log,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    if bearer_token is None:
        click.echo()
        click.echo("👋  Hi I don't see a configuration file yet, so lets make one.")
        click.echo()
        click.echo("Please follow these steps:")
        click.echo()
        click.echo("1. visit https://developer.twitter.com/en/portal/")
        click.echo("2. create a project and an app")
        click.echo("3. go to your Keys and Tokens and generate your keys and bearer token")
        click.echo()
        ctx.invoke(configure)
    else:
        ctx.obj = twarc.Twarc2(bearer_token)


@cli.command('configure')
@click.pass_context
def configure(ctx):
    """
    Set up your Twitter app bearer token.
    """
    prompt = "Please enter your bearer token: "
    bearer_token = input(prompt)

    config_dir = pathlib.Path(click.get_app_dir('twarc'))
    if not config_dir.is_dir():
        config_dir.mkdir()
    config_file = config_dir / "config"

    config = configobj.ConfigObj(unrepr=True)
    config.filename = config_file
    config['bearer_token'] = bearer_token
    config.write()

    click.echo('\n✨ ✨ ✨  Happy twarcing! ✨ ✨ ✨\n')
    ctx.exit()


@cli.command('search')
@click.option('--since-id', type=int,
    help='Match tweets sent after tweet id')
@click.option('--until-id', type=int,
    help='Match tweets sent prior to tweet id')
@click.option('--start-time',
    type=click.DateTime(formats=('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S')),
    help='Match tweets created after time (ISO 8601/RFC 3339), e.g.  2021-01-01T12:31:04')
@click.option('--end-time',
    type=click.DateTime(formats=('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S')),
    help='Match tweets sent before time (ISO 8601/RFC 3339)')
@click.option('--archive', is_flag=True, default=False,
    help='Search the full archive (requires Academic Research track)')
@click.option('--limit', default=0, help='Maximum number of tweets to save')
@click.option('--flatten', is_flag=True, default=False,
    help='Include expansions inline with tweets, and one line per tweet') 
@click.argument('query', type=str)
@click.argument('outfile', type=click.File('w'), default='-')
@click.pass_obj
@cli_api_error
def search(T, query, outfile, since_id, until_id, start_time, end_time, limit, archive, flatten):
    """
    Search for recent tweets.
    """
    count = 0
    for result in T.search(query, since_id, until_id, start_time, end_time, archive):
        _write(result, outfile, flatten)
        count += len(result['data'])
        if limit != 0 and count >= limit:
            break


@cli.command('sample')
@click.option('--limit', default=0, help='Maximum number of tweets to save')
@click.option('--flatten', is_flag=True, default=False,
    help='Include expansions inline with tweets, and one line per tweet.') 
@click.argument('outfile', type=click.File('w'), default='-')
@click.pass_obj
@cli_api_error
def sample(T, flatten, outfile, limit):
    """
    Fetch tweets from the sample stream.
    """
    count = 0
    event = threading.Event()
    for result in T.sample(event=event):
        count += 1
        if limit != 0 and count >= limit:
            event.set()
        _write(result, outfile, flatten)


@cli.command('hydrate')
@click.argument('infile', type=click.File('r'), default='-')
@click.argument('outfile', type=click.File('w'), default='-')
@click.option('--flatten', is_flag=True, default=False,
    help='Include expansions inline with tweets, and one line per tweet.') 
@click.pass_obj
@cli_api_error
def hydrate(T, infile, outfile, flatten):
    """
    Hydrate tweet ids from a file or stdin to a file or stdout.
    """
    for result in T.tweet_lookup(infile):
        _write(result, outfile, flatten)


@cli.command('users')
@click.option('--usernames', is_flag=True, default=False)
@click.option('--flatten', is_flag=True, default=False,
    help='Include expansions inline with tweets, and one line per tweet.') 
@click.argument('infile', type=click.File('r'), default='-')
@click.argument('outfile', type=click.File('w'), default='-')
@click.pass_obj
@cli_api_error
def users(T, infile, outfile, usernames, flatten):
    """
    Get data for user ids or usernames.
    """
    for result in T.user_lookup(infile, usernames):
        _write(result, outfile, flatten)


@cli.command('flatten')
@click.argument('infile', type=click.File('r'), default='-')
@click.argument('outfile', type=click.File('w'), default='-')
@cli_api_error
def flatten(infile, outfile):
    """
    "Flatten" tweets, or move expansions inline with tweet objects.
    """
    for line in infile:
        result = json.loads(line)
        _flatten(result, outfile, True)


@cli.command('stream')
@click.option('--limit', default=0, help='Maximum number of tweets to return')
@click.option('--flatten', is_flag=True, default=False,
    help='Include expansions inline with tweets, and one line per tweet') 
@click.argument('outfile', type=click.File('w'), default='-')
@click.pass_obj
@cli_api_error
def stream(T, flatten, outfile, limit):
    """
    Fetch tweets from the live stream.
    """
    event = threading.Event()
    count = 0
    for result in T.stream(event=event):
        count += 1
        if limit != 0 and count == limit:
            logging.info(f'reached limit {limit}')
            event.set()
        _write(result, outfile, flatten)


@cli.group()
@click.pass_obj
def stream_rules(T):
    """
    List, add and delete rules for your stream.
    """
    pass


@stream_rules.command('list')
@click.pass_obj
@cli_api_error
def list_stream_rules(T):
    """
    List all the active stream rules.
    """
    result = T.get_stream_rules()
    if 'data' not in result or len(result['data']) == 0:
        click.echo('No rules yet. Add them with ' + click.style('twarc2 stream-rules add', bold=True))
    else:
        count = 0
        for rule in result['data']:
            if count > 5:
                count = 0
            s = rule['value']
            if 'tag' in rule:
                s += f" (tag: {rule['tag']})"
            click.echo(click.style(f'☑  {s}'))
            count += 1


@stream_rules.command('add')
@click.pass_obj
@click.option('--tag', type=str, help='a tag to help identify the rule')
@click.argument('value', type=str)
@cli_api_error
def add_stream_rule(T, value, tag):
    """
    Create a new stream rule to match a value. Rules can be grouped with
    optional tags.
    """
    if tag:
        rules = [{"value": value, "tag": tag}]
    else:
        rules = [{"value": value}] 

    results = T.add_stream_rules(rules)
    if 'errors' in results:
        click.echo(_error_str(results['errors']), err=True)
    else:
        click.echo(click.style(f'🚀  Added rule for ', fg='green') + f'"{value}"')


@stream_rules.command('delete')
@click.argument('value')
@click.pass_obj
@cli_api_error
def delete_stream_rule(T, value):
    """
    Delete the stream rule that matches a given value.
    """
    # find the rule id
    result = T.get_stream_rules()
    if 'data' not in result:
        click.echo(click.style('💔  There are no rules to delete!', fg='red'), err=True)
    else:
        rule_id = None
        for rule in result['data']:
            if rule['value'] == value:
                rule_id = rule['id']
                break
        if not rule_id:
            click.echo(click.style(f'🙃  No rule could be found for "{value}"',
                fg='red'), err=True)
        else:
            results = T.delete_stream_rule_ids([rule_id])
            if 'errors' in results:
                click.echo(_error_str(results['errors']), err=True)
            else:
                click.echo(f"🗑  Deleted stream rule for {value}", color='green') 


@stream_rules.command('delete-all')
@click.pass_obj
@cli_api_error
def delete_all(T):
    """
    Delete all stream rules!
    """
    result = T.get_stream_rules()
    if 'data' not in result:
        click.echo(click.style('💔  There are no rules to delete!', fg='red'), err=True)
    else:
        rule_ids = [r['id'] for r in result['data']]
        results = T.delete_stream_rule_ids(rule_ids)
        click.echo(f"🗑  Deleted {len(rule_ids)} rules.")


def _rule_str(rule):
    s = f"id={rule['id']} value={rule['value']}"
    if 'tag' in rule:
        s += f" tag={rule['tag']}"
    return s


def _error_str(errors):
    # collapse all the error messages into a newline delimited red colored list
    # the passed in errors can be single error object or a list of objects, each 
    # of which has an errors key that points to a list of error objects

    if type(errors) != list or "errors" not in errors:
        errors = [{"errors": errors}]

    parts = []
    for error in errors:
        for part in error['errors']:
            s = "💣  "
            if 'message' in part:
                s += click.style(part['message'], fg='red')
            elif 'title' in part:
                s += click.style(part['title'], fg='red')
            else:
                s = click.style('Unknown error', fg='red')
            if 'type' in part:
                s += f" see: {part['type']}"
            parts.append(s)

    return click.style("\n".join(parts), fg="red")

def _write(results, outfile, flatten):
    if 'data' in results:
        if flatten:
            if isinstance(results['data'], list):
                for r in flat(results)['data']:
                    click.echo(json.dumps(r), file=outfile)
            else:
                r = flat(results)['data']
                click.echo(json.dumps(r), file=outfile)
        else:
            click.echo(json.dumps(results), file=outfile)
