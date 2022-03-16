from typing import List, Optional, Dict
import json
import asyncio
import logging
import argparse
import uvloop
from concurrent.futures import ThreadPoolExecutor

from ..utils import tqdm
from . import Transfer, Copier
from .router_fs import RouterAsyncFS
from .utils import make_tqdm_listener


async def copy(*,
               max_simultaneous_transfers: Optional[int] = None,
               local_kwargs: Optional[dict] = None,
               gcs_kwargs: Optional[dict] = None,
               azure_kwargs: Optional[dict] = None,
               s3_kwargs: Optional[dict] = None,
               transfers: List[Transfer]
               ) -> None:
    with ThreadPoolExecutor() as thread_pool:
        if max_simultaneous_transfers is None:
            max_simultaneous_transfers = 75
        if local_kwargs is None:
            local_kwargs = {}
        if 'thread_pool' not in local_kwargs:
            local_kwargs['thread_pool'] = thread_pool

        if s3_kwargs is None:
            s3_kwargs = {}
        if 'thread_pool' not in s3_kwargs:
            s3_kwargs['thread_pool'] = thread_pool

        async with RouterAsyncFS(default_scheme='file',
                                 local_kwargs=local_kwargs,
                                 gcs_kwargs=gcs_kwargs,
                                 azure_kwargs=azure_kwargs,
                                 s3_kwargs=s3_kwargs) as fs:
            sema = asyncio.Semaphore(max_simultaneous_transfers)
            async with sema:
                with tqdm(desc='files', leave=False, position=0, unit='file') as file_pbar, \
                     tqdm(desc='bytes', leave=False, position=1, unit='byte', unit_scale=True, smoothing=0.1) as byte_pbar:
                    copy_report = await Copier.copy(
                        fs,
                        sema,
                        transfers,
                        files_listener=make_tqdm_listener(file_pbar),
                        bytes_listener=make_tqdm_listener(byte_pbar))
                copy_report.summarize()


def make_transfer(json_object: Dict[str, str]) -> Transfer:
    if 'to' in json_object:
        return Transfer(json_object['from'], json_object['to'], treat_dest_as=Transfer.DEST_IS_TARGET)
    assert 'into' in json_object
    return Transfer(json_object['from'], json_object['into'], treat_dest_as=Transfer.DEST_DIR)


async def copy_from_dict(*,
                         max_simultaneous_transfers: Optional[int] = None,
                         local_kwargs: Optional[dict] = None,
                         gcs_kwargs: Optional[dict] = None,
                         azure_kwargs: Optional[dict] = None,
                         s3_kwargs: Optional[dict] = None,
                         files: List[Dict[str, str]]
                         ) -> None:
    transfers = [make_transfer(json_object) for json_object in files]
    await copy(
        max_simultaneous_transfers=max_simultaneous_transfers,
        local_kwargs=local_kwargs,
        gcs_kwargs=gcs_kwargs,
        azure_kwargs=azure_kwargs,
        s3_kwargs=s3_kwargs,
        transfers=transfers
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description='Hail copy tool')
    parser.add_argument('requester_pays_project', type=str,
                        help='a JSON string indicating the Google project to which to charge egress costs')
    parser.add_argument('files', type=str,
                        help='a JSON array of JSON objects indicating from where and to where to copy files')
    parser.add_argument('--max-simultaneous-transfers', type=int,
                        help='The limit on the number of simultaneous transfers. Large files are uploaded as multiple transfers. This parameter sets an upper bound on the number of open source and destination files.')
    parser.add_argument('-v', '--verbose', action='store_const',
                        const=True, default=False,
                        help='show logging information')
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig()
        logging.root.setLevel(logging.INFO)

    requester_pays_project = json.loads(args.requester_pays_project)
    files = json.loads(args.files)
    gcs_kwargs = {'project': requester_pays_project}

    await copy_from_dict(
        max_simultaneous_transfers=args.max_simultaneous_transfers,
        gcs_kwargs=gcs_kwargs,
        files=files
    )


if __name__ == '__main__':
    uvloop.install()
    asyncio.run(main())
