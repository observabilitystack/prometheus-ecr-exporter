import boto3
import botocore
import logging

from prometheus_client.core import InfoMetricFamily, GaugeMetricFamily, CounterMetricFamily
from cachetools import TTLCache


def _ecr_client():
    boto_config = botocore.client.Config(connect_timeout=2, read_timeout=10, retries={"max_attempts": 2})
    session = boto3.session.Session()
    return session.client('ecr', config=boto_config)


class ECRMetricsCollector():
    
    def __init__(self, registry_id):
        self.logger = logging.getLogger()
        self.registry_id = registry_id or _ecr_client().describe_registry()['registryId']
        self.repocache = TTLCache(1, 86400)
        self.imagecache = TTLCache(1000, 86400)
        
    def collect(self):
        repositories = self.repocache.get('cache')
    
        if repositories is None:
            self.refresh_repository_cache()
            repositories = self.repocache.get('cache')
        else:
            self.logger.debug('fetched repositories from cache')
                    
        repository_count_metric = GaugeMetricFamily(
            'ecr_repository_count',
            'Total count of all ECR repositories',
            labels = ['registry_id']
        )
        
        repository_count_metric.add_metric([self.registry_id], len(repositories))
    
        repository_info_metrics = InfoMetricFamily(
            'ecr_repository',
            'ECR repository information'
        )
    
        for repo in repositories:
            repository_info_metrics.add_metric([], {
                'name': repo['repositoryName'],
                'registry_id': repo['registryId'],
                'repository_uri': repo['repositoryUri'],
                'tag_mutability': repo['imageTagMutability'],
                'scan_on_push': str(repo['imageScanningConfiguration']['scanOnPush']).lower(),
                'encryption_type': repo['encryptionConfiguration']['encryptionType']        
            })
        
        image_size_metrics = GaugeMetricFamily(
            'ecr_image_size_in_bytes',
            'The size of an image in bytes',
            labels=['name', 'tag', 'digest', 'registry_id']
        )
        
        image_scan_metrics = GaugeMetricFamily(
            'ecr_image_scan_severity_count',
            'ECR image scan summary results',
            labels=['name', 'tag', 'digest', 'registry_id', 'severity']
        )
        
        for repo in repositories: 
            images = self.imagecache.get(repo['repositoryName'])
            
            if images is None:
                self.refresh_image_cache(repositories)
                images = self.imagecache.get(repo['repositoryName'])
            else:
                self.logger.debug(f"fetched {repo['repositoryName']} images from cache")
            
            for image in images:
                tags = image.get('imageTags')
                if tags:
                    for tag in tags:
                        image_size_metrics.add_metric([
                            repo['repositoryName'],
                            tag,
                            image['imageDigest'],
                            self.registry_id
                            ],
                        int(image['imageSizeInBytes'])
                        )
                    
                    scan_summary = image.get('imageScanFindingsSummary')
                    if scan_summary and scan_summary.get('findingSeverityCounts'):
                        severity_counts = scan_summary.get('findingSeverityCounts')
                        for severity in severity_counts:
                            image_scan_metrics.add_metric([
                                repo['repositoryName'],
                                tag,
                                image['imageDigest'],
                                self.registry_id,
                                severity
                                ],
                            int(severity_counts[severity])
                            )
                
        
        return [
                   repository_count_metric, 
                   repository_info_metrics,
                   image_size_metrics,
                   image_scan_metrics
               ]

    def refresh_repository_cache(self):
        ecr_client = _ecr_client()
        self.logger.info('refreshing repositories cache')
        repositories = ecr_client.describe_repositories(
            registryId=self.registry_id,
            maxResults=1000)['repositories']
            
        self.logger.debug(f'caching {len(repositories)} repositories')
        self.repocache['cache'] = repositories
        
    def refresh_image_cache(self, repositories, repository_name=''):
        ecr_client = _ecr_client()
        self.logger.info('refreshing image cache')
        for repo in repositories:
            images = ecr_client.describe_images(
                registryId=self.registry_id,
                repositoryName=repo['repositoryName'],
                filter={'tagStatus': 'TAGGED'},
                maxResults=1000)['imageDetails']
                
            self.imagecache[repo['repositoryName']] = images
            self.logger.debug(f"refreshed cache with {len(images)} images for {repo['repositoryName']}")
            
    def refresh_caches(self):
        self.refresh_repository_cache()
        repositories = self.repocache.get('cache')
        self.refresh_image_cache(repositories)